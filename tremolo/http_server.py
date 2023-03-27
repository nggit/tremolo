# Copyright (c) 2023 nggit

__all__ = ('HTTPServer',)

from datetime import datetime
from urllib.parse import parse_qs

from .exceptions import ExpectationFailed
from .lib.http_protocol import HTTPProtocol

class ServerContext:
    def __init__(self):
        self.__dict__ = {
            'options': {},
            'tasks': [],
            'data': {}
        }

    def __repr__(self):
        return self.__dict__.__repr__()

    @property
    def options(self):
        return self.__dict__['options']

    @property
    def tasks(self):
        return self.__dict__['tasks']

    @property
    def data(self):
        return self.__dict__['data']

    def set(self, name, value):
        self.__dict__[name] = value

class HTTPServer(HTTPProtocol):
    def __init__(self, **kwargs):
        self._route_handlers = kwargs['_handlers']
        self._middlewares = kwargs['_middlewares']
        self._server = {
            'loop': kwargs['loop'],
            'logger': kwargs['logger'],
            'socket': kwargs['sock'],
            'context': ServerContext(),
            'request': None,
            'response': None
        }

        super().__init__(self._server['context'], **kwargs)

    async def _connection_made(self, func):
        await func(**self._server)

        if self._server['context']._on_connect is not None:
            self._server['context']._on_connect.set_result(None)

    async def _connection_lost(self, func, exc):
        try:
            await func(**self._server)
        except Exception:
            pass

        super().connection_lost(exc)

    def connection_made(self, transport):
        super().connection_made(transport)

        func = self._middlewares['connect'][-1][0]
        self._server['context'].set('options', self._middlewares['connect'][-1][1])

        if func is None:
            self._server['context']._on_connect = None
        else:
            self._server['context']._on_connect = self._server['loop'].create_future()

            self._server['context'].tasks.append(
                self._server['loop'].create_task(self._connection_made(func))
            )

    def connection_lost(self, exc):
        func = self._middlewares['close'][-1][0]

        if func is None:
            super().connection_lost(exc)
            return

        self._server['loop'].create_task(self._connection_lost(func, exc))

    def _set_base_header(self, options={}):
        if self._server['response'].header is None or self._server['response'].header[1] != b'':
            return

        options['server_name'] = options.get('server_name', self.options['server_name'])

        if isinstance(options['server_name'], str):
            options['server_name'] = options['server_name'].encode(encoding='latin-1')

        self._server['response'].append_header(b'Date: %s\r\nServer: %s\r\n' % (
                                               datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT').encode(encoding='latin-1'),
                                               options['server_name']))

    async def _handle_middleware(self, func, options={}):
        if self._server['response'].header is not None:
            self._set_base_header(options)
            self._server['context'].set('options', options)

        data = await func(**self._server)

        if data is None:
            return options

        if not isinstance(data, (bytes, bytearray, str)):
            return

        if 'status' in options:
            self._server['response'].set_status(*options['status'])

        if 'content_type' in options:
            self._server['response'].set_content_type(options['content_type'])

        encoding = ('utf-8',)

        if isinstance(data, tuple):
            data, *encoding = (*data, 'utf-8')

        if isinstance(data, str):
            data = data.encode(encoding=encoding[0])

        await self._server['response'].end(data)

    async def _handle_continue(self):
        if self._server['request'].http_continue:
            if self._server['request'].content_length > self.options['client_max_body_size']:
                raise ExpectationFailed

            await self._server['response'].send(b'HTTP/%s 100 Continue\r\n\r\n' % self._server['request'].version)

    async def _handle_response(self, func, options={}):
        options['rate'] = options.get('rate', self.options['download_rate'])
        options['buffer_size'] = options.get('buffer_size', self.options['buffer_size'])

        if 'status' in options:
            self._server['response'].set_status(*options['status'])

        if 'content_type' in options:
            self._server['response'].set_content_type(options['content_type'])

        self._set_base_header(options)

        self._server['context'].set('options', options)
        agen = func(**self._server)

        try:
            data = await agen.__anext__()
            is_agen = True
        except AttributeError:
            data = await agen

            if data is None:
                self._server['response'].close()
                return

            is_agen = False

        status = self._server['response'].get_status()
        no_content = status[0] in (204, 304) or 100 <= status[0] < 200
        self._server['response'].http_chunked = options.get(
            'chunked', self._server['request'].version == b'1.1' and self._server['request'].http_keepalive and not no_content
        )

        if self._server['response'].http_chunked:
            self._server['response'].append_header(b'Transfer-Encoding: chunked\r\n')

        if self._middlewares['send'][-1][0] is not None:
            self._server['response'].set_write_callback(
                lambda : self._handle_middleware(
                    self._middlewares['send'][-1][0], {**self._middlewares['send'][-1][1], **options})
            )

        self._server['response'].header = b'HTTP/%s %d %s\r\n' % (self._server['request'].version, *status)

        if is_agen:
            if no_content:
                self._server['response'].append_header(b'Connection: close\r\n\r\n')
            else:
                if not self._server['response'].http_chunked:
                    self._server['request'].http_keepalive = False

                self._server['response'].append_header(b'Content-Type: %s\r\nConnection: keep-alive\r\n\r\n' %
                                                       self._server['response'].get_content_type())

            if self._server['request'].method == b'HEAD' or no_content:
                await self._server['response'].write(None)
                return

            self.transport.set_write_buffer_limits(high=options['buffer_size'] * 4, low=options['buffer_size'] // 2)
            await self._server['response'].write(
                data, rate=options['rate'], buffer_size=options['buffer_size']
            )

            while True:
                try:
                    data = await agen.__anext__()

                    await self._server['response'].write(
                        data, rate=options['rate'], buffer_size=options['buffer_size']
                    )
                except StopAsyncIteration:
                    await self._server['response'].write(b'', throttle=False)
                    break
        else:
            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = (*data, 'utf-8')

            if isinstance(data, str):
                data = data.encode(encoding=encoding[0])

            if no_content or data == b'':
                self._server['response'].append_header(b'Connection: close\r\n\r\n')
            else:
                if self._server['response'].http_chunked:
                    self._server['response'].append_header(b'Content-Type: %s\r\nConnection: keep-alive\r\n\r\n'
                                                           % self._server['response'].get_content_type())
                else:
                    self._server['response'].append_header(
                        b'Content-Type: %s\r\nContent-Length: %d\r\nConnection: %s\r\n\r\n' % (
                        self._server['response'].get_content_type(), len(data), {
                            True: b'keep-alive',
                            False: b'close'}[self._server['request'].http_keepalive])
                    )

            if data == b'' or self._server['request'].method == b'HEAD' or no_content:
                await self._server['response'].write(None)
                return

            self.transport.set_write_buffer_limits(high=options['buffer_size'] * 4, low=options['buffer_size'] // 2)
            await self._server['response'].write(data, rate=options['rate'], buffer_size=options['buffer_size'])
            await self._server['response'].write(b'', throttle=False)

        await self._server['response'].send(None)

    async def header_received(self, request, response):
        self._server['request'] = request
        self._server['response'] = response

        if self._server['context']._on_connect is not None:
            await self._server['context']._on_connect
            self._server['context']._on_connect = None

        options = self._server['context'].options

        for middleware in self._middlewares['request']:
            options = await self._handle_middleware(middleware[0], {**middleware[1], **options})

            if not isinstance(options, dict):
                return

        if request.is_valid:
            qs_pos = request.path.find(b'?')

            if qs_pos > -1:
                path = request.path[:qs_pos]
                self._server['request'].query = parse_qs(request.path[qs_pos + 1:].decode(encoding='latin-1'))
            else:
                path = request.path

            p = path.strip(b'/')

            if p == b'':
                ri = 1
            else:
                ri = b'%d#%s' % (p.count(b'/') + 2, p[:(p + b'/').find(b'/')])

            if ri in self._route_handlers:
                for (pattern, func, kwargs) in self._route_handlers[ri]:
                    m = pattern.search(request.path)

                    if m:
                        await self._handle_continue()

                        matches = m.groupdict()

                        if not matches:
                            matches = m.groups()

                        self._server['request'].params['url'] = matches

                        await self._handle_response(func, {**kwargs, **options})
                        return
            else:
                for i, (pattern, func, kwargs) in enumerate(self._route_handlers[-1]):
                    m = pattern.search(request.path)

                    if m:
                        if ri in self._route_handlers:
                            self._route_handlers[ri].append((pattern, func, kwargs))
                        else:
                            self._route_handlers[ri] = [(pattern, func, kwargs)]

                        await self._handle_continue()

                        matches = m.groupdict()

                        if not matches:
                            matches = m.groups()

                        self._server['request'].params['url'] = matches

                        await self._handle_response(func, {**kwargs, **options})
                        del self._route_handlers[-1][i]
                        return

            # not found
            await self._handle_response(self._route_handlers[0][1][1], {**self._route_handlers[0][1][2], **options})
        else:
            # bad request
            await self._handle_response(self._route_handlers[0][0][1], {**self._route_handlers[0][0][2], **options})
