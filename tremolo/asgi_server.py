# Copyright (c) 2023 nggit

import asyncio

from http import HTTPStatus
from urllib.parse import unquote_to_bytes

from .exceptions import (
    Forbidden,
    InternalServerError,
    WebSocketClientClosed,
    WebSocketServerClosed
)
from .handlers import error_400
from .lib.http_protocol import HTTPProtocol
from .lib.websocket import WebSocket


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

        # provide direct access to server objects
        scope['state']['server'] = dict(self.server, response=response)

        if (self.options['ws'] and b'sec-websocket-key' in request.headers and
                b'upgrade' in request.headers and
                request.headers[b'upgrade'][0].lower() == b'websocket'):
            scope['type'] = 'websocket'
            scope['scheme'] = b'wss' if request.scheme == b'https' else b'ws'
            scope['subprotocols'] = [
                value.decode('latin-1') for value in
                request.headers.getlist(b'sec-websocket-protocol')]
        else:
            scope['type'] = 'http'
            scope['method'] = request.method.decode('latin-1')
            scope['scheme'] = request.scheme.decode('latin-1')

        app = ASGIAppWrapper(self, self.options['app'], scope, response)

        try:
            await app

            if 'close' in self.events and not self.events['close'].done():
                self.logger.info('handler exited early (no close?)')
                await self.events['close']
        except (asyncio.CancelledError, Exception) as exc:
            if app.response is None:  # already sent
                self.print_exception(exc, 'app')
            else:
                if scope['type'] == 'websocket' and request.upgraded:
                    exc = WebSocketServerClosed(cause=exc)

                await response.handle_exception(exc, 'app')
        finally:
            scope.clear()


class ASGIAppWrapper:
    def __init__(self, protocol, app, scope, response):
        self.protocol = protocol
        self.app = app
        self.scope = scope
        self.request = response.request
        self.response = response
        self.loop = protocol.loop
        self.logger = protocol.logger

        self._websocket = None

    def __await__(self):
        return self.app(self.scope, self.receive, self.send).__await__()

    async def receive(self):
        if self.scope['type'] == 'websocket':
            # initially, the Request.upgraded value is False
            # it will become True later
            # after the response status is set to 101:
            # Response.set_status(101) in WebSocket.accept()
            if not self.request.upgraded and self._websocket is None:
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
            except Exception as exc:
                code = 1005

                if self._websocket is None or self.protocol.is_closing():
                    self.logger.info(
                        'calling receive() after the connection is closed'
                    )
                else:
                    if isinstance(exc, WebSocketClientClosed):
                        code = exc.code
                    else:
                        self.protocol.print_exception(exc, 'receive')

                    if isinstance(exc, WebSocketServerClosed):
                        await self._websocket.close(exc.code)
                    else:
                        await self._websocket.close(1011 if code == 1005
                                                    else 1000)

                    self.protocol.request = None  # force handler timeout
                    self.protocol.set_handler_timeout(
                        self.protocol.options['app_close_timeout']
                    )
                    self._websocket = None
                    self.response = None

                return {
                    'type': 'websocket.disconnect',
                    'code': code
                }

        try:
            data = await self.request.read()

            if not data:
                self.request = None

            return {
                'type': 'http.request',
                'body': data,
                'more_body': bool(data)
            }
        except Exception as exc:
            if self.response is None or self.protocol.is_closing():
                self.logger.info(
                    'calling receive() after the connection is closed'
                )
            else:
                if self.request is None:
                    # delay http.disconnect. see:
                    # https://github.com/nggit/tremolo/issues/202
                    if self.protocol.events['close'].done():
                        self.protocol.events[
                            'close'] = self.loop.create_future()

                    self.logger.info(
                        'calling receive() when there is no more body'
                    )
                    try:
                        await self.protocol.events['close']
                    except asyncio.CancelledError:
                        if self.response is not None:  # not a wake up
                            raise
                else:
                    await self.response.handle_exception(exc, 'receive')

                self.protocol.set_handler_timeout(
                    self.protocol.options['app_close_timeout']
                )
                self.response = None

            return {'type': 'http.disconnect'}

    async def send(self, data):
        try:
            if data['type'] in ('http.response.start', 'websocket.accept'):
                if self.response.line is not None:
                    raise InternalServerError('already started or accepted')

                # websocket doesn't have this
                if 'status' in data:
                    self.response.set_status(data['status'],
                                             HTTPStatus(data['status']).phrase)

                if 'headers' in data:
                    for header in data['headers']:
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
                                self.response.request.http_keepalive = False

                            continue

                        if name == b'content-length':
                            # will disable http chunked in the
                            # self.response.write()
                            self.response.http_chunked = False

                        self.response.append_header(*header)

                # websocket has this
                if 'subprotocol' in data and data['subprotocol']:
                    self.response.set_header(
                        b'Sec-WebSocket-Protocol', data['subprotocol']
                    )
            elif self.response.line is None:
                if data['type'] == 'websocket.close':
                    self._websocket = None
                    raise Forbidden('connection rejected')

                raise InternalServerError('has not been started or accepted')

            if (data['type'] == 'http.response.body' and
                    self._websocket is None):
                if 'body' in data and data['body'] != b'':
                    await self.response.write(
                        data['body'],
                        rate=self.protocol.options['download_rate'],
                        buffer_size=self.protocol.options['buffer_size']
                    )

                if 'more_body' not in data or not data['more_body']:
                    await self.response.write(b'')
                    self.response.close(keepalive=True)
                    self.request = None  # disallows further receive()
                    self.response = None
                    self.protocol.events['close'].cancel()  # wake up receive()
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
                self.response = None
            elif data['type'] != 'http.response.start':
                raise InternalServerError('unexpected ASGI message type')
        except (asyncio.CancelledError, Exception) as exc:
            if self.response is None or self.protocol.is_closing():
                self.logger.info(
                    'calling send() after the connection is closed'
                )
            else:
                if self.scope['type'] == 'websocket' and self.request.upgraded:
                    exc = WebSocketServerClosed(cause=exc)

                await self.response.handle_exception(exc, 'send')
                self.response = None  # disallows further send()
