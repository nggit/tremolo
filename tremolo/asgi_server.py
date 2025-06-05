# Copyright (c) 2023 nggit

import asyncio

from http import HTTPStatus
from urllib.parse import unquote_to_bytes

from .exceptions import (
    InternalServerError,
    WebSocketException,
    WebSocketClientClosed,
    WebSocketServerClosed
)
from .handlers import error_400
from .lib.http_protocol import HTTPProtocol
from .lib.websocket import WebSocket

_WSS_OR_WS = {
    False: 'ws',
    True: 'wss'
}


class ASGIServer(HTTPProtocol):
    def connection_made(self, transport):
        super().connection_made(transport)

        self.events['close'] = self.loop.create_future()

    def connection_lost(self, exc):
        if not self.events['close'].done():
            self.events['close'].set_result(None)

        super().connection_lost(exc)

    async def request_received(self, request, response):
        if not request.is_valid:
            await error_400(request=request, response=response)
            return

        scope = {
            'asgi': {'version': '3.0', 'spec_version': '2.3'},
            'root_path': self.options['root_path'],
            'server': self.globals.info['server'],
            'client': request.client,
            'http_version': request.version.decode('latin-1'),
            'path': unquote_to_bytes(request.path).decode('latin-1'),
            'raw_path': request.path,
            'query_string': request.query_string,
            'headers': request.header.getheaders(),
            'state': self.options['state'].copy()
        }

        if self.options['experimental']:
            # provide direct access to server objects
            scope['state']['server'] = {**self.server, 'response': response}

        if (self.options['ws'] and b'sec-websocket-key' in request.headers and
                b'upgrade' in request.headers and
                request.headers[b'upgrade'].lower() == b'websocket'):
            scope['type'] = 'websocket'
            scope['scheme'] = _WSS_OR_WS[request.scheme == b'https']
            scope['subprotocols'] = [
                value.decode('latin-1') for value in
                request.headers.getlist(b'sec-websocket-protocol')]
        else:
            scope['type'] = 'http'
            scope['method'] = request.method.decode('latin-1')
            scope['scheme'] = request.scheme.decode('latin-1')

        try:
            await ASGIWrapper(self.options['app'], scope, request, response)

            if not self.events['close'].done():
                self.logger.info('handler exited early (no close?)')
                await self.events['close']
        except (asyncio.CancelledError, Exception) as exc:
            if scope['type'] == 'websocket' and request.upgraded:
                exc = WebSocketServerClosed(cause=exc)

            await response.handle_exception(exc)
        finally:
            scope.clear()


class ASGIWrapper:
    def __init__(self, app, scope, request, response):
        self.app = app
        self.scope = scope
        self.request = request
        self.response = response
        self.loop = request.server.loop
        self.logger = request.server.logger

        self._stream = request.stream()
        self._websocket = None

    def __await__(self):
        return self.app(self.scope, self.receive, self.send).__await__()

    @property
    def protocol(self):  # don't cache request.protocol
        return self.request.protocol

    async def receive(self):
        if self.scope['type'] == 'websocket':
            # initially, the Request.upgraded value is False
            # it will become True later
            # after the response status is set to 101:
            # Response.set_status(101) in WebSocket.accept()
            if not self.request.upgraded and self._websocket is None:
                await self._stream.aclose()
                self._websocket = WebSocket(self.request, self.response)

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
                code = 1011

                if self._websocket is None or self.protocol is None:
                    code = 1005
                    self.logger.info(
                        'calling receive() after the connection is closed'
                    )
                else:
                    if isinstance(exc, WebSocketException):
                        code = exc.code

                    if not isinstance(exc, WebSocketClientClosed):
                        self.protocol.print_exception(exc)
                        await self._websocket.close(code)

                    self.protocol.request = None  # force handler timeout
                    self.protocol.set_handler_timeout(
                        self.protocol.options['app_close_timeout']
                    )
                return {
                    'type': 'websocket.disconnect',
                    'code': code
                }

        try:
            data = await self._stream.__anext__()
            more_body = self.request.has_body and not self.request.eof()

            if not more_body:
                self._stream = None

            return {
                'type': 'http.request',
                'body': data,
                'more_body': more_body
            }
        except (asyncio.CancelledError, Exception) as exc:
            if self.protocol is None or self.protocol.is_closing():
                self.logger.info(
                    'calling receive() after the connection is closed'
                )
            else:
                if self._stream is None or isinstance(exc, StopAsyncIteration):
                    # delay http.disconnect (a workaround for Quart)
                    # https://github.com/nggit/tremolo/issues/202
                    if self.protocol.events['close'].done():
                        self.protocol.events[
                            'close'] = self.loop.create_future()

                    if self._stream is not None:
                        self._stream = None
                        return {'type': 'http.request'}

                    self.logger.info(
                        'calling receive() when there is no more body'
                    )
                    await self.protocol.events['close']
                else:
                    await self.response.handle_exception(exc)

                self.protocol.set_handler_timeout(
                    self.protocol.options['app_close_timeout']
                )
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
                        rate=self.protocol.options['download_rate'],
                        buffer_size=self.protocol.options['buffer_size']
                    )

                if 'more_body' not in data or data['more_body'] is False:
                    await self.response.write(b'')
                    self.response.close(keepalive=True)
                    self._stream = None  # disallows further receive()
                    self.protocol.events['close'].cancel()
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
                self.protocol.events['close'].cancel()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if self.response is None or self.protocol is None:
                self.logger.info(
                    'calling send() after the connection is closed'
                )
            else:
                self.protocol.print_exception(exc)
                self.response = None  # disallows further send()
