# Copyright (c) 2023 nggit

import asyncio

from datetime import datetime
from http import HTTPStatus
from urllib.parse import unquote

from .contexts import ServerContext
from .exceptions import (
    ExpectationFailed,
    InternalServerError,
    WebSocketException,
    WebSocketClientClosed
)
from .lib.http_protocol import HTTPProtocol
from .lib.websocket import WebSocket


class ASGIServer(HTTPProtocol):
    __slots__ = ('_app',
                 '_scope',
                 '_read',
                 '_task',
                 '_timer',
                 '_timeout',
                 '_websocket')

    def __init__(self, _app=None, **kwargs):
        self._app = _app
        self._scope = None
        self._read = None
        self._task = None
        self._timer = None
        self._timeout = 30
        self._websocket = None

        super().__init__(ServerContext(), **kwargs)

    def _handle_websocket(self):
        self._websocket = WebSocket(self.request, self.response)

        self._scope['type'] = 'websocket'
        self._scope['scheme'] = {
            True: 'ws',
            False: 'wss'
        }[self.request.transport.get_extra_info('sslcontext') is None]
        self._scope['subprotocols'] = [
            value.decode('utf-8') for value in
            self.request.headers.getlist(b'sec-websocket-protocol')]

    async def _handle_http(self):
        if self.request.http_continue:
            if (self.request.content_length >
                    self.options['client_max_body_size']):
                raise ExpectationFailed

            await self.response.send(b'HTTP/%s 100 Continue\r\n\r\n' %
                                     self.request.version)

        self._scope['type'] = 'http'
        self._scope['method'] = self.request.method.decode('utf-8')
        self._scope['scheme'] = {
            True: 'http',
            False: 'https'
        }[self.request.transport.get_extra_info('sslcontext') is None]

        if not (b'transfer-encoding' in self.request.headers or
                b'content-length' in self.request.headers
                ) and self.queue[0] is not None:
            # avoid blocking on initial receive() due to empty Queue
            # in the case of bodyless requests, e.g. GET
            self.queue[0].put_nowait(b'')

    async def header_received(self):
        self._scope = {
            'asgi': {'version': '3.0'},
            'http_version': self.request.version.decode('utf-8'),
            'path': unquote(self.request.path.decode('utf-8'), 'utf-8'),
            'raw_path': self.request.path,
            'query_string': self.request.query_string,
            'root_path': self.options['_root_path'],
            'headers': self.request.header.getheaders(),
            'client': self.request.client,
            'server': self.request.transport.get_extra_info('sockname')
        }

        if (self.options['ws'] and b'upgrade' in self.request.headers and
                b'connection' in self.request.headers and
                b'sec-websocket-key' in self.request.headers and
                self.request.headers[b'upgrade'].lower() == b'websocket'):
            self._handle_websocket()
        else:
            await self._handle_http()
            self._read = self.request.stream()

        self._task = self.loop.create_task(self.app())

    def connection_lost(self, exc):
        if (self._task is not None and not self._task.done() and
                self._timer is None):
            self._timer = self.loop.call_at(self.loop.time() + self._timeout,
                                            self._task.cancel)

        super().connection_lost(exc)

    async def app(self):
        try:
            await self._app(self._scope, self.receive, self.send)

            if self._timer is not None:
                self._timer.cancel()
        except asyncio.CancelledError:
            self.logger.warning(
                'task: ASGI application is cancelled due to timeout'
            )
        except Exception as exc:
            await self.handle_exception(exc)

    def _set_app_timeout(self):
        if self._timer is None:
            self._timer = self.loop.call_at(
                self.loop.time() + self._timeout, self._task.cancel
            )

    async def receive(self):
        if self._scope['type'] == 'websocket':
            # initially, the Request.upgraded value is False
            # it will become True later
            # after the response status is set to 101:
            # Response.set_status(101) in WebSocket.accept()
            if not self.request.upgraded:
                return {'type': 'websocket.connect'}

            try:
                payload = await self._websocket.receive()

                if isinstance(payload, str):
                    return {
                        'type': 'websocket.receive',
                        'text': payload
                    }

                return {
                    'type': 'websocket.receive',
                    'bytes': payload
                }
            except WebSocketException as exc:
                code = 1005

                if isinstance(exc, WebSocketClientClosed):
                    code = exc.code

                if self.request is not None:
                    self.print_exception(exc)

                self._set_app_timeout()
                return {
                    'type': 'websocket.disconnect',
                    'code': code
                }

        if self._scope['type'] != 'http':
            await self.handle_exception(
                InternalServerError('unsupported scope type {:s}'
                                    .format(self._scope['type']))
            )
            return

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

            self._set_app_timeout()
            return {'type': 'http.disconnect'}

    async def send(self, data):
        try:
            if data['type'] in ('http.response.start', 'websocket.accept'):
                # websocket doesn't have this
                if 'status' in data:
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
                                    b'transfer-encoding',
                                    b'sec-websocket-protocol'):
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

                # websocket has this
                if 'subprotocol' in data and data['subprotocol']:
                    if '\n' in data['subprotocol']:
                        await self.handle_exception(
                            InternalServerError(
                                'subprotocol value cannot contain '
                                'illegal characters')
                        )
                        return

                    self.response.append_header(
                        b'Sec-WebSocket-Protocol: %s\r\n' %
                        data['subprotocol'].encode('utf-8')
                    )

            if data['type'] == 'http.response.body':
                if 'body' in data:
                    await self.response.write(data['body'])

                if 'more_body' not in data or data['more_body'] is False:
                    await self.response.write(b'', throttle=False)
                    await self.response.send(None)
            elif data['type'] == 'websocket.send':
                if 'bytes' in data and data['bytes']:
                    await self._websocket.send(data['bytes'])
                elif 'text' in data and data['text']:
                    await self._websocket.send(data['text'], opcode=1)
            elif data['type'] == 'websocket.accept':
                await self._websocket.accept()
            elif data['type'] == 'websocket.close':
                await self._websocket.close(data.get('code', 1000))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not (self.request is None or self.response is None):
                self.print_exception(exc)
