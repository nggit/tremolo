# Copyright (c) 2023 nggit

from .lib.contexts import ServerContext
from .lib.http_protocol import HTTPProtocol
from .lib.http_response import KEEPALIVE_OR_CLOSE, KEEPALIVE_OR_UPGRADE
from .lib.sse import SSE
from .lib.tasks import ServerTasks
from .lib.websocket import WebSocket


class HTTPServer(HTTPProtocol):
    __slots__ = ('_routes', '_middlewares', '_server')

    def __init__(self, _routes=None, _middlewares=None, lock=None, **kwargs):
        self._routes = _routes
        self._middlewares = _middlewares
        self._server = {
            'loop': kwargs['loop'],
            'logger': kwargs['logger'],
            'worker': kwargs['worker'],
            'lock': lock,
            'context': ServerContext()
        }

        super().__init__(self._server['context'], **kwargs)

    async def _connection_made(self):
        for func, _ in self._middlewares['connect']:
            if await func(**self._server):
                break

    async def _connection_lost(self, exc):
        try:
            i = len(self._middlewares['close'])

            while i > 0:
                i -= 1

                if await self._middlewares['close'][i][0](**self._server):
                    break
        finally:
            super().connection_lost(exc)

    def connection_made(self, transport):
        super().connection_made(transport)

        if self._middlewares['connect']:
            self.context.ON_CONNECT = self.loop.create_task(
                self._connection_made()
            )
            self.tasks.append(self.context.ON_CONNECT)

    def connection_lost(self, exc):
        if self._middlewares['close']:
            task = self.loop.create_task(self._connection_lost(exc))
            self.loop.call_at(
                self.loop.time() + self.options['_app_close_timeout'],
                task.cancel)
        else:
            super().connection_lost(exc)

    async def _handle_middleware(self, func, options={}):
        self.response.set_base_header()
        self.context.set('options', options)

        data = await func(**self._server,
                          request=self.request,
                          response=self.response)

        if data is None:
            return options

        if not isinstance(data, (bytes, bytearray, str, tuple)):
            self.logger.info('middleware %s has exited with the connection '
                             'possibly left open', func.__name__)
            return

        if 'status' in options:
            self.response.set_status(*options['status'])

        if 'content_type' in options:
            self.response.set_content_type(options['content_type'])

        encoding = ('utf-8',)

        if isinstance(data, tuple):
            data, *encoding = (*data, 'utf-8')

        if isinstance(data, str):
            data = data.encode(encoding[0])

        await self.response.end(data)

    def _handle_websocket(self):
        if (self.options['ws'] and b'upgrade' in self.request.headers and
                b'connection' in self.request.headers and
                b'sec-websocket-key' in self.request.headers and
                self.request.headers[b'upgrade'].lower() == b'websocket'):
            self._server['websocket'] = WebSocket(self.request, self.response)

    async def _handle_response(self, func, options={}):
        options['rate'] = options.get('rate', self.options['download_rate'])
        options['buffer_size'] = options.get('buffer_size',
                                             self.options['buffer_size'])

        if not self.request.has_body:
            if 'websocket' in options:
                self._handle_websocket()

            if 'sse' in options:
                self._server['sse'] = SSE(self.request, self.response)

        if 'tasks' in options:
            self._server['tasks'] = ServerTasks(self.tasks, loop=self.loop)

        if 'status' in options:
            self.response.set_status(*options['status'])

        if 'content_type' in options:
            self.response.set_content_type(options['content_type'])

        self.response.set_base_header()
        self.context.set('options', options)

        agen = func(**self._server,
                    request=self.request, response=self.response)
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
        self.response.headers[b'_line'] = [b'HTTP/%s' % self.request.version,
                                           b'%d' % status[0],
                                           status[1]]

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
                    KEEPALIVE_OR_UPGRADE[status[0] in (101, 426)]
                )
            else:
                self.response.set_header(b'Connection', b'close')

            i = len(self._middlewares['response'])

            while i > 0:
                i -= 1
                options = await self._handle_middleware(
                    self._middlewares['response'][i][0],
                    {**self._middlewares['response'][i][1], **options}
                )

                if not isinstance(options, dict):
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
                        b'', throttle=False, buffer_min_size=buffer_min_size
                    )
                    break
        else:
            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = (*data, 'utf-8')

            if isinstance(data, str):
                data = data.encode(encoding[0])

            if not (no_content or self.response.http_chunked):
                self.response.set_header(b'Content-Length', b'%d' % len(data))

            self.response.set_header(
                b'Connection', KEEPALIVE_OR_CLOSE[self.request.http_keepalive]
            )

            i = len(self._middlewares['response'])

            while i > 0:
                i -= 1
                options = await self._handle_middleware(
                    self._middlewares['response'][i][0],
                    {**self._middlewares['response'][i][1], **options}
                )

                if not isinstance(options, dict):
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

            await self.response.write(b'', throttle=False)

        self.response.close(keepalive=True)

    async def headers_received(self):
        if self._middlewares['connect']:
            await self.context.ON_CONNECT

        options = {}

        for middleware in self._middlewares['request']:
            options = await self._handle_middleware(
                middleware[0],
                {**middleware[1], **options}
            )

            if not isinstance(options, dict):
                return

        if not self.request.is_valid:
            # bad request
            await self._handle_response(
                self._routes[0][0][1],
                {**self._routes[0][0][2], **options}
            )
            return

        _path = self.request.path.strip(b'/')

        if _path == b'':
            key = 1
        else:
            key = b'%d#%s' % (
                _path.count(b'/') + 2, _path[:(_path + b'/').find(b'/')]
            )

        if key in self._routes:
            for (pattern, func, kwargs) in self._routes[key]:
                m = pattern.search(self.request.url)

                if m:
                    matches = m.groupdict()

                    if not matches:
                        matches = m.groups()

                    self.request.params['path'] = matches

                    await self._handle_response(func, {**kwargs, **options})
                    return
        else:
            i = len(self._routes[-1])

            while i > 0:
                i -= 1
                pattern, func, kwargs = self._routes[-1][i]
                m = pattern.search(self.request.url)

                if m:
                    if key in self._routes:
                        self._routes[key].append(
                            (pattern, func, kwargs)
                        )
                    else:
                        self._routes[key] = [(pattern, func, kwargs)]

                    matches = m.groupdict()

                    if not matches:
                        matches = m.groups()

                    self.request.params['path'] = matches

                    await self._handle_response(func, {**kwargs, **options})
                    del self._routes[-1][i]
                    return

        # not found
        await self._handle_response(
            self._routes[0][1][1],
            {**self._routes[0][1][2], **options}
        )

    async def handle_error_500(self, exc):
        # internal server error
        return await self._routes[0][-1][1](request=self.request,
                                            response=self.response,
                                            exc=exc)
