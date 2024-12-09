# Copyright (c) 2023 nggit

import asyncio

from http import HTTPStatus
from urllib.parse import unquote_to_bytes

from .exceptions import (
    InternalServerError,
    WebSocketClientClosed,
    WebSocketServerClosed
)
from .handlers import error_400, error_500
from .lib.http_protocol import HTTPProtocol
from .lib.websocket import WebSocket

_WS_OR_WSS = {
    False: 'ws',
    True: 'wss'
}


class ASGIServer(HTTPProtocol):
    __slots__ = ('response', '_scope', '_read', '_websocket', '_timer')

    def __init__(self, context, **kwargs):
        super().__init__(context, **kwargs)

        self.response = None  # set in headers_received
        self._scope = {
            'asgi': {'version': '3.0', 'spec_version': '2.3'},
            'root_path': self.options['_root_path'],
            'server': self.globals.info['server']
        }
        self._read = None
        self._websocket = None
        self._timer = None

    def _handle_websocket(self):
        self._websocket = WebSocket(self.request, self.response)

        self._scope['type'] = 'websocket'
        self._scope['scheme'] = _WS_OR_WSS[self.request.scheme == b'https']
        self._scope['subprotocols'] = [
            value.decode('latin-1') for value in
            self.request.headers.getlist(b'sec-websocket-protocol')]

    def _handle_http(self):
        self._read = self.request.stream()

        self._scope['type'] = 'http'
        self._scope['method'] = self.request.method.decode('latin-1')
        self._scope['scheme'] = self.request.scheme.decode('latin-1')

    async def headers_received(self, response):
        self.response = response

        if not self.request.is_valid:
            await error_400(request=self.request, response=response)
            return

        self._scope.update(
            http_version=self.request.version.decode('latin-1'),
            path=unquote_to_bytes(self.request.path).decode('latin-1'),
            raw_path=self.request.path,
            query_string=self.request.query_string,
            headers=self.request.header.getheaders(),
            client=self.request.client
        )

        if (self.options['ws'] and b'upgrade' in self.request.headers and
                b'connection' in self.request.headers and
                b'sec-websocket-key' in self.request.headers and
                self.request.headers[b'upgrade'].lower() == b'websocket'):
            self._handle_websocket()
        else:
            self._handle_http()

        try:
            await self.options['_app'](self._scope, self.receive, self.send)
        except (asyncio.CancelledError, Exception) as exc:
            if (self.request is not None and self.request.upgraded and
                    self._websocket is not None):
                exc = WebSocketServerClosed(cause=exc)

            await response.handle_exception(exc)
        finally:
            if self._timer is not None:
                self._timer.cancel()

    async def error_received(self, exc):
        if self.request is not None and self.response is not None:
            return await error_500(
                request=self.request, response=self.response, exc=exc
            )

    def connection_lost(self, exc):
        if self.handler is not None and not self.handler.done():
            self._set_app_close_timeout()

        super().connection_lost(exc)
        self.response = None
        self._scope = None

    def _set_app_close_timeout(self):
        if self._timer is None:
            self._timer = self.loop.call_at(
                self.loop.time() + self.options['_app_close_timeout'],
                self.handler.cancel
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
            except (asyncio.CancelledError, Exception) as exc:
                code = 1005

                if isinstance(exc, WebSocketClientClosed):
                    code = exc.code

                if not (self._websocket is None or self.request is None):
                    self.print_exception(exc)

                self._set_app_close_timeout()
                return {
                    'type': 'websocket.disconnect',
                    'code': code
                }

        if self._scope['type'] != 'http':
            await self.response.handle_exception(
                InternalServerError('unsupported scope type %s' %
                                    self._scope['type'])
            )
            return

        try:
            data = await self._read.__anext__()

            return {
                'type': 'http.request',
                'body': data,
                'more_body': (
                    (data != b'' and self.request.content_length == -1) or
                    self.request.body_consumed < self.request.content_length
                )
            }
        except (asyncio.CancelledError, Exception) as exc:
            if not (self._read is None or self.request is None or
                    isinstance(exc, StopAsyncIteration)):
                self.print_exception(exc)

            self._set_app_close_timeout()
            return {'type': 'http.disconnect'}

    async def send(self, data):
        try:
            if data['type'] in ('http.response.start', 'websocket.accept'):
                # websocket doesn't have this
                if 'status' in data:
                    self.response.set_status(data['status'],
                                             HTTPStatus(data['status']).phrase)

                if 'headers' in data:
                    for header in data['headers']:
                        if b'\n' in header[0] or b'\n' in header[1]:
                            await self.response.handle_exception(
                                InternalServerError(
                                    'name or value cannot contain '
                                    'illegal characters')
                            )
                            return

                        name = header[0].lower()

                        if name == b'content-type':
                            self.response.set_content_type(header[1])
                            continue

                        if name in (b'date', b'server', b'transfer-encoding'):
                            # disallow apps from changing them,
                            # as they are managed by Tremolo
                            continue

                        if name == b'connection':
                            if header[1].lower() == b'close':
                                self.request.http_keepalive = False

                            continue

                        if name == b'content-length':
                            # will disable http chunked in the
                            # self.response.write()
                            self.response.http_chunked = False

                        self.response.append_header(*header)

                # websocket has this
                if 'subprotocol' in data and data['subprotocol']:
                    if '\n' in data['subprotocol']:
                        await self.response.handle_exception(
                            InternalServerError(
                                'subprotocol value cannot contain '
                                'illegal characters')
                        )
                        return

                    self.response.set_header(
                        b'Sec-WebSocket-Protocol',
                        data['subprotocol'].encode('utf-8')
                    )

            if data['type'] == 'http.response.body':
                if 'body' in data and data['body'] != b'':
                    await self.response.write(
                        data['body'],
                        throttle=self.response.headers_sent(),
                        buffer_size=self.options['buffer_size']
                    )

                if 'more_body' not in data or data['more_body'] is False:
                    await self.response.write(b'', throttle=False)
                    self.response.close(keepalive=True)
                    self._read = None
            elif data['type'] == 'websocket.send':
                if 'bytes' in data and data['bytes']:
                    await self._websocket.send(data['bytes'])
                elif 'text' in data and data['text']:
                    await self._websocket.send(data['text'], opcode=1)
            elif data['type'] == 'websocket.accept':
                await self._websocket.accept()
            elif data['type'] == 'websocket.close':
                await self._websocket.close(data.get('code', 1000))
                self._websocket = None
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not (self.request is None or self.response is None):
                self.print_exception(exc)
