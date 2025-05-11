# Copyright (c) 2023 nggit

from asyncio import iscoroutine

from .lib.http_protocol import HTTPProtocol
from .lib.http_response import KEEPALIVE_OR_CLOSE, UPGRADE_OR_KEEPALIVE
from .lib.sse import SSE
from .lib.websocket import WebSocket


class HTTPServer(HTTPProtocol):
    async def _connection_made(self):
        for _, func, _ in self.app.middlewares['connect']:
            if await func(**self.server):
                break

    async def _connection_lost(self, exc):
        try:
            i = len(self.app.middlewares['close'])

            while i > 0:
                i -= 1

                if await self.app.middlewares['close'][i][1](**self.server):
                    break
        finally:
            super().connection_lost(exc)

    def connection_made(self, transport):
        super().connection_made(transport)

        if self.app.middlewares['connect']:
            self.context.ON_CONNECT = self.app.create_task(
                self._connection_made()
            )
            self.add_task(self.context.ON_CONNECT)

    def connection_lost(self, exc):
        if self.app.middlewares['close']:
            task = self.app.create_task(self._connection_lost(exc))
            self.loop.call_at(
                self.loop.time() + self.options['app_close_timeout'],
                task.cancel
            )
        else:
            super().connection_lost(exc)

    async def run_middlewares(self, name, reverse=False, step=1):
        if self.is_closing():
            return

        if reverse and self.server['next'] != -1:
            self.server['next'] = len(self.app.middlewares[name]) - 1
            step = -1

        while -1 < self.server['next'] < len(self.app.middlewares[name]):
            middleware = self.app.middlewares[name][self.server['next']]

            if await self._handle_middleware(middleware[1], middleware[2]):
                if reverse:
                    self.server['next'] = -1
                else:
                    self.server['next'] = len(self.app.middlewares[name])

                return True

            self.server['next'] += step

    async def _handle_middleware(self, func, kwargs):
        response = self.server['response']
        options = response.request.context.options
        options.update(kwargs)

        data = await func(**self.server)

        if data is None:
            return False

        if isinstance(data, (bytes, bytearray, str, tuple)):
            if 'status' in options:
                response.set_status(*options['status'])

            if 'content_type' in options:
                response.set_content_type(options['content_type'])

            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = data + encoding

            if isinstance(data, str):
                data = data.encode(encoding[0])

            await response.end(data)
        else:
            self.logger.info('middleware %s has exited with the connection '
                             'possibly left open', func.__name__)

        return True

    async def _handle_response(self, func, kwargs):
        response = self.server['response']
        request = response.request
        options = request.context.options
        options.update(kwargs)
        options.setdefault('rate', self.options['download_rate'])
        options.setdefault('buffer_size', self.options['buffer_size'])

        if not request.has_body:
            if ('websocket' in options and self.options['ws'] and
                    b'sec-websocket-key' in request.headers and
                    b'upgrade' in request.headers and
                    request.headers[b'upgrade'].lower() == b'websocket'):
                self.server['websocket'] = WebSocket(request, response)

            if 'sse' in options:
                self.server['sse'] = SSE(request, response)

        if 'status' in options:
            response.set_status(*options['status'])

        if 'content_type' in options:
            response.set_content_type(options['content_type'])

        try:
            agen = func(**self.server)
        except TypeError:  # doesn't accept extra **kwargs
            agen = func(**{k: self.server.get(k, kwargs[k]) for k in kwargs})

        next_data = getattr(agen, '__anext__', False)

        if next_data:
            data = await next_data()
        else:
            if not iscoroutine(agen):
                data = agen
            else:
                data = await agen

            if data is None:
                response.close()
                return

            if not isinstance(data, (bytes, bytearray, str, tuple)):
                self.logger.info('handler %s has exited with the connection '
                                 'possibly left open', func.__name__)
                return

        status = response.get_status()
        no_content = status[0] in (204, 205, 304) or 100 <= status[0] < 200
        response.http_chunked = options.get(
            'chunked', request.version == b'1.1' and not no_content
        )
        response.set_status(*status)

        if not no_content:
            response.set_header(b'Content-Type', response.get_content_type())

        if response.http_chunked:
            response.set_header(b'Transfer-Encoding', b'chunked')

        if next_data:
            if request.http_keepalive:
                if status[0] == 101:
                    request.upgraded = True
                elif not (response.http_chunked or
                          b'content-length' in response.headers):
                    # no chunk, no close, no size.
                    # Assume close to signal end
                    request.http_keepalive = False

                response.set_header(
                    b'Connection',
                    UPGRADE_OR_KEEPALIVE[status[0] in (101, 426)]
                )
            else:
                response.set_header(b'Connection', b'close')

            if await self.run_middlewares('response', reverse=True):
                return

            if request.method == b'HEAD' or no_content:
                await response.write()
                return

            buffer_min_size = options['buffer_size'] // 2
            self.set_watermarks(high=options['buffer_size'] * 4,
                                low=buffer_min_size)

            if options.get('stream', True):
                buffer_min_size = None

            if data != b'':
                await response.write(data,
                                     rate=options['rate'],
                                     buffer_size=options['buffer_size'],
                                     buffer_min_size=buffer_min_size)

            while True:
                try:
                    data = await next_data()

                    if data == b'':
                        continue

                    await response.write(data,
                                         rate=options['rate'],
                                         buffer_size=options['buffer_size'],
                                         buffer_min_size=buffer_min_size)
                except StopAsyncIteration:
                    await response.write(b'', buffer_min_size=buffer_min_size)
                    break
        else:
            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = data + encoding

            if isinstance(data, str):
                data = data.encode(encoding[0])

            if not (no_content or response.http_chunked):
                response.set_header(b'Content-Length', b'%d' % len(data))

            response.set_header(
                b'Connection', KEEPALIVE_OR_CLOSE[request.http_keepalive]
            )

            if await self.run_middlewares('response', reverse=True):
                return

            if request.method == b'HEAD' or no_content:
                await response.write()
                return

            if data != b'':
                self.set_watermarks(high=options['buffer_size'] * 4,
                                    low=options['buffer_size'] // 2)
                await response.write(data,
                                     rate=options['rate'],
                                     buffer_size=options['buffer_size'])

            await response.write(b'')

        response.close(keepalive=True)

    async def request_received(self, request, response):
        self.server['response'] = response
        self.server['next'] = 0

        if self.app.middlewares['connect']:
            await self.context.ON_CONNECT

        if await self.run_middlewares('request'):
            await self.run_middlewares('response', reverse=True)
            return

        if not request.is_valid:
            # bad request
            await self._handle_response(
                self.app.routes[0][0][1], self.app.routes[0][0][2]
            )
            return

        path = request.path.strip(b'/')

        if path == b'':
            key = 1
        else:
            parts = path.split(b'/', 254)
            key = bytes([len(parts)]) + parts[0]

        if key in self.app.routes:
            for pattern, func, kwargs in self.app.routes[key]:
                m = pattern.search(request.url)

                if m:
                    matches = m.groupdict()

                    if not matches:
                        matches = m.groups()

                    request.params['path'] = matches

                    await self._handle_response(func, kwargs)
                    return
        else:
            i = len(self.app.routes[-1])

            while i > 0:
                i -= 1
                pattern, func, kwargs = self.app.routes[-1][i]
                m = pattern.search(request.url)

                if m:
                    if key in self.app.routes:
                        self.app.routes[key].append((pattern, func, kwargs))
                    else:
                        self.app.routes[key] = [(pattern, func, kwargs)]

                    matches = m.groupdict()

                    if not matches:
                        matches = m.groups()

                    request.params['path'] = matches

                    await self._handle_response(func, kwargs)
                    del self.app.routes[-1][i]
                    return

        # not found
        await self._handle_response(
            self.app.routes[0][1][1], self.app.routes[0][1][2]
        )
