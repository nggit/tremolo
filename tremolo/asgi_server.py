# Copyright (c) 2023 nggit

__all__ = ('ASGIServer',)

import asyncio

from datetime import datetime
from http import HTTPStatus
from urllib.parse import unquote

from .contexts import ServerContext
from .exceptions import ExpectationFailed, InternalServerError
from .lib.http_protocol import HTTPProtocol

class ASGIServer(HTTPProtocol):
    def __init__(self, **kwargs):
        self._app = kwargs['_app']
        self._request = None
        self._response = None
        self._read = None
        self._task = None
        self._timer = None
        self._timeout = 30

        super().__init__(ServerContext(), **kwargs)

    async def header_received(self, request, response):
        if request.http_continue:
            if request.content_length > self.options['client_max_body_size']:
                raise ExpectationFailed

            await response.send(b'HTTP/%s 100 Continue\r\n\r\n' % request.version)

        scope = {
            'type': 'http',
            'asgi': {'version': '3.0'},
            'http_version': request.version.decode(encoding='utf-8'),
            'method': request.method.decode(encoding='utf-8'),
            'scheme': {True: 'http',
                       False: 'https'}[request.transport.get_extra_info('sslcontext') is None],
            'path': unquote(request.path.decode(encoding='utf-8'), encoding='utf-8'),
            'raw_path': request.path,
            'query_string': request.query_string,
            'headers': request.protocol.header.getheaders(),
            'client': request.transport.get_extra_info('peername'),
            'server': request.transport.get_extra_info('sockname')
        }

        self._request = request
        self._response = response
        self._read = request.read(cache=False)

        if not (b'transfer-encoding' in request.headers or b'content-length' in request.headers
                ) and self.queue[0] is not None:
            # avoid blocking on initial receive() due to empty Queue
            # in the case of bodyless requests, e.g. GET
            self.queue[0].put_nowait(b'')

        self._task = self.loop.create_task(self.app(scope))

    def connection_lost(self, exc):
        if self._task is not None and not self._task.done() and self._timer is None:
            self._timer = self.loop.call_at(self.loop.time() + self._timeout, self._task.cancel)

        super().connection_lost(exc)

    async def app(self, scope):
        try:
            await self._app(scope, self.receive, self.send)

            if self._timer is not None:
                self._timer.cancel()
        except asyncio.CancelledError:
            self.options['logger'].warning('task: ASGI application is cancelled due to timeout')
        except Exception as exc:
            await self.handle_exception(InternalServerError(cause=exc), self._request, self._response)

    async def receive(self):
        try:
            data = await self._read.__anext__()

            return {
                'type': 'http.request',
                'body': data,
                'more_body': ((data != b'' and self._request.content_length == -1)
                    or self._request.body_size < self._request.content_length)
            }
        except Exception as exc:
            if not (self._request is None or isinstance(exc, StopAsyncIteration)):
                self.print_exception(exc)

            if self._timer is None:
                self._timer = self.loop.call_at(self.loop.time() + self._timeout, self._task.cancel)

            return {'type': 'http.disconnect'}

    async def send(self, data):
        try:
            if data['type'] == 'http.response.start':
                self._response.set_status(data['status'], HTTPStatus(data['status']).phrase)
                self._response.append_header(b'Date: %s\r\nServer: %s\r\n' % (
                                             datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT').encode(encoding='latin-1'),
                                             self.options['server_name']))

                if 'headers' in data:
                    for header in data['headers']:
                        if header[0] == b'content-type':
                            self._response.set_content_type(header[1])
                            continue

                        if header[0] in (b'connection', b'date', b'server', b'transfer-encoding'):
                            # disallow apps from changing them, as they are managed by Tremolo
                            continue

                        if header[0] == b'content-length':
                            # will disable http chunked in the self._response.write()
                            self._request.http_keepalive = False

                        self._response.append_header(b'%s: %s\r\n' % header)
            elif data['type'] == 'http.response.body':
                if 'body' in data:
                    await self._response.write(data['body'])

                if 'more_body' not in data or data['more_body'] is False:
                    await self._response.write(b'', throttle=False)
                    await self._response.send(None)
        except Exception as exc:
            if not (self._request is None or self._response is None):
                self.print_exception(exc)
