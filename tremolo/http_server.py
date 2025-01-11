# Copyright (c) 2023 nggit

from .lib.http_protocol import HTTPProtocol
from .lib.http_response import KEEPALIVE_OR_CLOSE, UPGRADE_OR_KEEPALIVE
from .lib.sse import SSE
from .lib.websocket import WebSocket


class HTTPServer(HTTPProtocol):
    __slots__ = ('_routes', '_middlewares', '_server')

    def __init__(self, context, _routes=None, _middlewares=None, **kwargs):
        super().__init__(context, **kwargs)

        self._routes = _routes
        self._middlewares = _middlewares
        self._server = {
            'response': None,  # set in headers_received
            'globals': context,
            'context': self.context,
            'loop': kwargs['loop'],
            'logger': kwargs['logger'],
            'lock': kwargs['lock']
        }

    @property
    def response(self):
        return self._server['response']

    async def _connection_made(self):
        for _, func, _ in self._middlewares['connect']:
            if await func(**self._server):
                break

    async def _connection_lost(self, exc):
        try:
            i = len(self._middlewares['close'])

            while i > 0:
                i -= 1

                if await self._middlewares['close'][i][1](**self._server):
                    break
        finally:
            super().connection_lost(exc)

    def connection_made(self, transport):
        super().connection_made(transport)

        if self._middlewares['connect']:
            self.context.ON_CONNECT = self.create_background_task(
                self._connection_made()
            )
            self.add_close_callback(self.context.ON_CONNECT.cancel)

    def connection_lost(self, exc):
        if self._middlewares['close']:
            task = self.create_background_task(self._connection_lost(exc))
            self.loop.call_at(
                self.loop.time() + self.options['app_close_timeout'],
                task.cancel
            )
        else:
            super().connection_lost(exc)

        self._server['response'] = None

    async def run_middlewares(self, name, reverse=False, start=0, step=1):
        if reverse:
            start = len(self._middlewares[name]) - 1
            step = -1

        while 0 <= start < len(self._middlewares[name]):
            if await self._handle_middleware(
                    self._middlewares[name][start][1],
                    self._middlewares[name][start][2]):
                return True

            start += step

    async def _handle_middleware(self, func, kwargs):
        options = self.request.context.options
        options.update(kwargs)

        data = await func(**self._server)

        if data is None:
            return False

        if isinstance(data, (bytes, bytearray, str, tuple)):
            if 'status' in options:
                self.response.set_status(*options['status'])

            if 'content_type' in options:
                self.response.set_content_type(options['content_type'])

            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = data + encoding

            if isinstance(data, str):
                data = data.encode(encoding[0])

            await self.response.end(data)
        else:
            self.logger.info('middleware %s has exited with the connection '
                             'possibly left open', func.__name__)

        return True

    def _handle_websocket(self):
        if (self.options['ws'] and b'upgrade' in self.request.headers and
                b'connection' in self.request.headers and
                b'sec-websocket-key' in self.request.headers and
                self.request.headers[b'upgrade'].lower() == b'websocket'):
            self._server['websocket'] = WebSocket(self.request, self.response)

    async def _handle_response(self, func, kwargs):
        options = self.request.context.options
        options.update(kwargs)
        options.setdefault('rate', self.options['download_rate'])
        options.setdefault('buffer_size', self.options['buffer_size'])

        if not self.request.has_body:
            if 'websocket' in options:
                self._handle_websocket()

            if 'sse' in options:
                self._server['sse'] = SSE(self.request, self.response)

        if 'status' in options:
            self.response.set_status(*options['status'])

        if 'content_type' in options:
            self.response.set_content_type(options['content_type'])

        try:
            agen = func(**self._server)
        except TypeError:  # doesn't accept extra **kwargs
            agen = func(**{k: self._server.get(k, kwargs[k]) for k in kwargs})

        next_data = getattr(agen, '__anext__', False)

        if next_data:
            data = await next_data()
        else:
            data = await agen

            if data is None:
                self.response.close()
                return

            if not isinstance(data, (bytes, bytearray, str, tuple)):
                self.logger.info('handler %s has exited with the connection '
                                 'possibly left open', func.__name__)
                return

        status = self.response.get_status()
        no_content = status[0] in (204, 205, 304) or 100 <= status[0] < 200
        self.response.http_chunked = options.get(
            'chunked', self.request.version == b'1.1' and not no_content
        )
        self.response.set_status(*status)

        if not no_content:
            self.response.set_header(
                b'Content-Type', self.response.get_content_type()
            )

        if self.response.http_chunked:
            self.response.set_header(b'Transfer-Encoding', b'chunked')

        if next_data:
            if self.request.http_keepalive:
                if status[0] == 101:
                    self.request.upgraded = True
                elif not (self.response.http_chunked or
                          b'content-length' in self.response.headers):
                    # no chunk, no close, no size.
                    # Assume close to signal end
                    self.request.http_keepalive = False

                self.response.set_header(
                    b'Connection',
                    UPGRADE_OR_KEEPALIVE[status[0] in (101, 426)]
                )
            else:
                self.response.set_header(b'Connection', b'close')

            if await self.run_middlewares('response', reverse=True):
                return

            if self.request.method == b'HEAD' or no_content:
                await self.response.write(None)
                return

            buffer_min_size = options['buffer_size'] // 2

            self.set_watermarks(high=options['buffer_size'] * 4,
                                low=buffer_min_size)

            if options.get('stream', True):
                buffer_min_size = None

            if data != b'':
                await self.response.write(data,
                                          rate=options['rate'],
                                          buffer_size=options['buffer_size'],
                                          buffer_min_size=buffer_min_size)

            while True:
                try:
                    data = await next_data()

                    if data == b'':
                        continue

                    await self.response.write(
                        data,
                        rate=options['rate'],
                        buffer_size=options['buffer_size'],
                        buffer_min_size=buffer_min_size
                    )
                except StopAsyncIteration:
                    await self.response.write(
                        b'', buffer_min_size=buffer_min_size
                    )
                    break
        else:
            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = data + encoding

            if isinstance(data, str):
                data = data.encode(encoding[0])

            if not (no_content or self.response.http_chunked):
                self.response.set_header(b'Content-Length', b'%d' % len(data))

            self.response.set_header(
                b'Connection', KEEPALIVE_OR_CLOSE[self.request.http_keepalive]
            )

            if await self.run_middlewares('response', reverse=True):
                return

            if self.request.method == b'HEAD' or no_content:
                await self.response.write(None)
                return

            if data != b'':
                self.set_watermarks(high=options['buffer_size'] * 4,
                                    low=options['buffer_size'] // 2)
                await self.response.write(data,
                                          rate=options['rate'],
                                          buffer_size=options['buffer_size'])

            await self.response.write(b'')

        self.response.close(keepalive=True)

    async def headers_received(self, response):
        self._server['response'] = response
        self._server['request'] = self.request

        if self._middlewares['connect']:
            await self.context.ON_CONNECT

        if await self.run_middlewares('request'):
            return

        if not self.request.is_valid:
            # bad request
            await self._handle_response(
                self._routes[0][0][1], self._routes[0][0][2]
            )
            return

        path = self.request.path.strip(b'/')

        if path == b'':
            key = 1
        else:
            parts = path.split(b'/', 254)
            key = bytes([len(parts)]) + parts[0]

        if key in self._routes:
            for (pattern, func, kwargs) in self._routes[key]:
                m = pattern.search(self.request.url)

                if m:
                    matches = m.groupdict()

                    if not matches:
                        matches = m.groups()

                    self.request.params['path'] = matches

                    await self._handle_response(func, kwargs)
                    return
        else:
            i = len(self._routes[-1])

            while i > 0:
                i -= 1
                pattern, func, kwargs = self._routes[-1][i]
                m = pattern.search(self.request.url)

                if m:
                    if key in self._routes:
                        self._routes[key].append((pattern, func, kwargs))
                    else:
                        self._routes[key] = [(pattern, func, kwargs)]

                    matches = m.groupdict()

                    if not matches:
                        matches = m.groups()

                    self.request.params['path'] = matches

                    await self._handle_response(func, kwargs)
                    del self._routes[-1][i]
                    return

        # not found
        await self._handle_response(
            self._routes[0][1][1], self._routes[0][1][2]
        )

    async def error_received(self, exc):
        # internal server error
        if self.request is not None and self.response is not None:
            return await self._routes[0][-1][1](request=self.request,
                                                response=self.response,
                                                exc=exc)
