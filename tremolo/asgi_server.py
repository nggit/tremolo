# Copyright (c) 2023 nggit

__all__ = ('ASGIServer',)

import asyncio  # noqa: E402

from datetime import datetime  # noqa: E402
from http import HTTPStatus  # noqa: E402
from urllib.parse import unquote  # noqa: E402

from .contexts import ServerContext  # noqa: E402
from .exceptions import ExpectationFailed, InternalServerError  # noqa: E402
from .lib.http_protocol import HTTPProtocol  # noqa: E402


class ASGIServer(HTTPProtocol):
    def __init__(self, **kwargs):
        self._app = kwargs['_app']
        self._read = None
        self._task = None
        self._timer = None
        self._timeout = 30

        super().__init__(ServerContext(), **kwargs)

    async def header_received(self):
        if self.request.http_continue:
            if (self.request.content_length >
                    self.options['client_max_body_size']):
                raise ExpectationFailed

            await self.response.send(b'HTTP/%s 100 Continue\r\n\r\n' %
                                     self.request.version)

        scope = {
            'type': 'http',
            'asgi': {'version': '3.0'},
            'http_version': self.request.version.decode('utf-8'),
            'method': self.request.method.decode('utf-8'),
            'scheme': {
                True: 'http',
                False: 'https'
            }[self.request.transport.get_extra_info('sslcontext') is None],
            'path': unquote(self.request.path.decode('utf-8'), 'utf-8'),
            'raw_path': self.request.path,
            'query_string': self.request.query_string,
            'root_path': self.options['_root_path'],
            'headers': self.request.header.getheaders(),
            'client': self.request.client,
            'server': self.request.transport.get_extra_info('sockname')
        }

        self._read = self.request.read(cache=False)

        if not (b'transfer-encoding' in self.request.headers or
                b'content-length' in self.request.headers
                ) and self.queue[0] is not None:
            # avoid blocking on initial receive() due to empty Queue
            # in the case of bodyless requests, e.g. GET
            self.queue[0].put_nowait(b'')

        self._task = self.loop.create_task(self.app(scope))

    def connection_lost(self, exc):
        if (self._task is not None and not self._task.done() and
                self._timer is None):
            self._timer = self.loop.call_at(self.loop.time() + self._timeout,
                                            self._task.cancel)

        super().connection_lost(exc)

    async def app(self, scope):
        try:
            await self._app(scope, self.receive, self.send)

            if self._timer is not None:
                self._timer.cancel()
        except asyncio.CancelledError:
            self.options['logger'].warning(
                'task: ASGI application is cancelled due to timeout'
            )
        except Exception as exc:
            await self.handle_exception(InternalServerError(cause=exc))

    async def receive(self):
        try:
            data = await self._read.__anext__()

            return {
                'type': 'http.request',
                'body': data,
                'more_body': (
                    (data != b'' and self.request.content_length == -1) or
                    self.request.body_size < self.request.content_length
                )
            }
        except Exception as exc:
            if not (self.request is None or
                    isinstance(exc, StopAsyncIteration)):
                self.print_exception(exc)

            if self._timer is None:
                self._timer = self.loop.call_at(
                    self.loop.time() + self._timeout, self._task.cancel
                )

            return {'type': 'http.disconnect'}

    async def send(self, data):
        try:
            if data['type'] == 'http.response.start':
                self.response.set_status(data['status'],
                                         HTTPStatus(data['status']).phrase)
                self.response.append_header(
                    b'Date: %s\r\nServer: %s\r\n' % (
                        datetime.utcnow().strftime(
                            '%a, %d %b %Y %H:%M:%S GMT').encode('latin-1'),
                        self.options['server_name'])
                )

                if 'headers' in data:
                    for header in data['headers']:
                        if b'\n' in header[0] or b'\n' in header[1]:
                            await self.handle_exception(
                                InternalServerError(
                                    'name or value cannot contain '
                                    'illegal characters')
                            )
                            return

                        name = header[0].lower()

                        if name == b'content-type':
                            self.response.set_content_type(header[1])
                            continue

                        if name in (b'connection',
                                    b'date',
                                    b'server',
                                    b'transfer-encoding'):
                            # disallow apps from changing them,
                            # as they are managed by Tremolo
                            continue

                        if name == b'content-length':
                            # will disable http chunked in the
                            # self.response.write()
                            self.request.http_keepalive = False

                        if isinstance(header, list):
                            header = tuple(header)

                        self.response.append_header(b'%s: %s\r\n' % header)
            elif data['type'] == 'http.response.body':
                if 'body' in data:
                    await self.response.write(data['body'])

                if 'more_body' not in data or data['more_body'] is False:
                    await self.response.write(b'', throttle=False)
                    await self.response.send(None)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not (self.request is None or self.response is None):
                self.print_exception(exc)
