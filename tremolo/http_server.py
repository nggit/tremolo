# Copyright (c) 2023 nggit

__all__ = ('HTTPServer',)

from datetime import datetime  # noqa: E402
from urllib.parse import parse_qs  # noqa: E402

from .contexts import ServerContext  # noqa: E402
from .exceptions import ExpectationFailed  # noqa: E402
from .lib.http_protocol import HTTPProtocol  # noqa: E402


class HTTPServer(HTTPProtocol):
    def __init__(self, **kwargs):
        self._route_handlers = kwargs['_handlers']
        self._middlewares = kwargs['_middlewares']
        self._server = {
            'loop': kwargs['loop'],
            'logger': kwargs['logger'],
            'lock': kwargs['lock'],
            'socket': kwargs['sock'],
            'context': ServerContext()
        }

        super().__init__(self._server['context'], **kwargs)

    async def _connection_made(self, func):
        await func(**self._server)

    async def _connection_lost(self, func, exc):
        try:
            await func(**self._server)
        finally:
            super().connection_lost(exc)

    def connection_made(self, transport):
        super().connection_made(transport)

        func = self._middlewares['connect'][-1][0]
        self._server['context'].set(
            'options',
            self._middlewares['connect'][-1][1]
        )

        if func is None:
            self._server['context']._on_connect = None
        else:
            self._server['context']._on_connect = self._server['loop'].create_task(  # noqa: E501
                self._connection_made(func)
            )

            self._server['context'].tasks.append(
                self._server['context']._on_connect
            )

    def connection_lost(self, exc):
        func = self._middlewares['close'][-1][0]

        if func is None:
            super().connection_lost(exc)
            return

        self._server['loop'].create_task(self._connection_lost(func, exc))

    def _set_base_header(self, options={}):
        if self.response.header is None or self.response.header[1] != b'':
            return

        options['server_name'] = options.get('server_name',
                                             self.options['server_name'])

        if isinstance(options['server_name'], str):
            options['server_name'] = options['server_name'].encode('latin-1')

        self.response.append_header(
            b'Date: %s\r\nServer: %s\r\n' % (
                datetime.utcnow().strftime(
                    '%a, %d %b %Y %H:%M:%S GMT').encode('latin-1'),
                options['server_name'])
        )

    async def _handle_middleware(self, func, options={}):
        if self.response.header is not None:
            self._set_base_header(options)
            self._server['context'].set('options', options)

        data = await func(**self._server,
                          request=self.request,
                          response=self.response)

        if data is None:
            return options

        if not isinstance(data, (bytes, bytearray, str, tuple)):
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

    async def _handle_continue(self):
        if self.request.http_continue:
            if (self.request.content_length >
                    self.options['client_max_body_size']):
                raise ExpectationFailed

            await self.response.send(b'HTTP/%s 100 Continue\r\n\r\n' %
                                     self.request.version)

    async def _handle_response(self, func, options={}):
        options['rate'] = options.get('rate', self.options['download_rate'])
        options['buffer_size'] = options.get('buffer_size',
                                             self.options['buffer_size'])

        if 'status' in options:
            self.response.set_status(*options['status'])

        if 'content_type' in options:
            self.response.set_content_type(options['content_type'])

        self._set_base_header(options)

        self._server['context'].set('options', options)
        agen = func(**self._server,
                    request=self.request, response=self.response)

        try:
            data = await agen.__anext__()
            is_agen = True
        except AttributeError:
            data = await agen

            if data is None:
                self.response.close()
                return

            if not isinstance(data, (bytes, bytearray, str, tuple)):
                return

            is_agen = False

        status = self.response.get_status()
        no_content = status[0] in (204, 304) or 100 <= status[0] < 200
        self.response.http_chunked = options.get(
            'chunked', self.request.version == b'1.1' and
            self.request.http_keepalive and not no_content
        )

        if self.response.http_chunked:
            self.response.append_header(b'Transfer-Encoding: chunked\r\n')

        if self._middlewares['send'][-1][0] is not None:
            self.response.set_write_callback(
                lambda: self._handle_middleware(
                    self._middlewares['send'][-1][0],
                    {**self._middlewares['send'][-1][1], **options})
            )

        self.response.header = b'HTTP/%s %d %s\r\n' % (self.request.version,
                                                       *status)

        if is_agen:
            if no_content:
                self.response.append_header(b'Connection: close\r\n\r\n')
            else:
                if not self.response.http_chunked:
                    self.request.http_keepalive = False

                if status[0] == 101:
                    self.request.http_upgrade = True

                self.response.append_header(
                    b'Content-Type: %s\r\nConnection: %s\r\n\r\n' % (
                        self.response.get_content_type(),
                        {False: b'keep-alive',
                            True: b'upgrade'}[status[0] in (101, 426)])
                )

            if self.request.method == b'HEAD' or no_content:
                await self.response.write(None)
                return

            self.set_watermarks(high=options['buffer_size'] * 4,
                                low=options['buffer_size'] // 2)
            await self.response.write(
                data, rate=options['rate'], buffer_size=options['buffer_size']
            )

            while True:
                try:
                    data = await agen.__anext__()

                    await self.response.write(
                        data,
                        rate=options['rate'],
                        buffer_size=options['buffer_size']
                    )
                except StopAsyncIteration:
                    await self.response.write(b'', throttle=False)
                    break
        else:
            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = (*data, 'utf-8')

            if isinstance(data, str):
                data = data.encode(encoding[0])

            if no_content or data == b'':
                self.response.append_header(b'Connection: close\r\n\r\n')
            else:
                if self.response.http_chunked:
                    self.response.append_header(
                        b'Content-Type: %s\r\nConnection: keep-alive\r\n\r\n' %
                        self.response.get_content_type()
                    )
                else:
                    self.response.append_header(
                        b'Content-Type: %s\r\nContent-Length: %d\r\n'
                        b'Connection: %s\r\n\r\n' % (
                            self.response.get_content_type(), len(data), {
                                True: b'keep-alive',
                                False: b'close'}[self.request.http_keepalive])
                    )

            if data == b'' or self.request.method == b'HEAD' or no_content:
                await self.response.write(None)
                return

            self.set_watermarks(high=options['buffer_size'] * 4,
                                low=options['buffer_size'] // 2)
            await self.response.write(data,
                                      rate=options['rate'],
                                      buffer_size=options['buffer_size'])
            await self.response.write(b'', throttle=False)

        await self.response.send(None)

    async def header_received(self):
        if self._server['context']._on_connect is not None:
            await self._server['context']._on_connect

        options = self._server['context'].options

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
                self._route_handlers[0][0][1],
                {**self._route_handlers[0][0][2], **options}
            )
            return

        if self.request.query_string != b'':
            self.request.query = parse_qs(
                self.request.query_string.decode('latin-1')
            )

        _path = self.request.path.strip(b'/')

        if _path == b'':
            key = 1
        else:
            key = b'%d#%s' % (
                _path.count(b'/') + 2, _path[:(_path + b'/').find(b'/')]
            )

        if key in self._route_handlers:
            for (pattern, func, kwargs) in self._route_handlers[key]:
                m = pattern.search(self.request.url)

                if m:
                    await self._handle_continue()

                    matches = m.groupdict()

                    if not matches:
                        matches = m.groups()

                    self.request.params['path'] = matches

                    await self._handle_response(func, {**kwargs, **options})
                    return
        else:
            for i, (pattern,
                    func,
                    kwargs) in enumerate(self._route_handlers[-1]):
                m = pattern.search(self.request.url)

                if m:
                    if key in self._route_handlers:
                        self._route_handlers[key].append(
                            (pattern, func, kwargs)
                        )
                    else:
                        self._route_handlers[key] = [(pattern, func, kwargs)]

                    await self._handle_continue()

                    matches = m.groupdict()

                    if not matches:
                        matches = m.groups()

                    self.request.params['path'] = matches

                    await self._handle_response(func, {**kwargs, **options})
                    del self._route_handlers[-1][i]
                    return

        # not found
        await self._handle_response(
            self._route_handlers[0][1][1],
            {**self._route_handlers[0][1][2], **options}
        )
