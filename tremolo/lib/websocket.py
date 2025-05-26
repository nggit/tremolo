# Copyright (c) 2023 nggit

import base64
import hashlib
import os

from .http_exceptions import WebSocketClientClosed, WebSocketServerClosed

_MAGIC = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


class WebSocket:
    def __init__(self, request, response):
        self.request = request
        self.response = response
        self.fin = 1
        self.opcode = 0

        self._max_payload_size = request.server.options['ws_max_payload_size']
        self._receive_timeout = request.server.options['keepalive_timeout'] / 2

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.request.upgraded:
            await self.accept()

        try:
            return await self.receive()
        except WebSocketClientClosed as exc:
            await self.close()
            raise StopAsyncIteration from exc

    async def accept(self):
        sha1_hash = hashlib.sha1(  # nosec B303, B324
            self.request.headers[b'sec-websocket-key'] + _MAGIC
        ).digest()
        accept_key = base64.b64encode(sha1_hash)

        self.response.set_status(101, b'Switching Protocols')
        self.response.set_header(b'Upgrade', b'websocket')
        self.response.set_header(b'Sec-WebSocket-Accept', accept_key)
        await self.response.write()

    async def recv(self):
        try:
            first_byte, second_byte = await self.request.recv(2)
        except ValueError as exc:
            raise WebSocketClientClosed(
                'connection closed: recv failed'
            ) from exc

        fin = (first_byte & 0x80) >> 7
        opcode = first_byte & 0x0f
        is_masked = (second_byte & 0x80) >> 7
        payload_length = second_byte & 0x7f

        if opcode != 0:
            if self.fin != 1:
                raise WebSocketServerClosed('unexpected start', code=1002)

            if fin == 0:  # start of fragmented message
                self.fin = 0

            self.opcode = opcode
        else:  # continuation frame
            if self.fin == 1:
                raise WebSocketServerClosed('unexpected continuation',
                                            code=1002)

            if fin == 1:  # end of fragmented message, reset
                self.fin = 1

        if payload_length == 126:
            payload_length = int.from_bytes(await self.request.recv(2),
                                            byteorder='big')
        elif payload_length == 127:
            payload_length = int.from_bytes(await self.request.recv(8),
                                            byteorder='big')

            if payload_length > self._max_payload_size:
                raise WebSocketServerClosed(
                    '%d exceeds maximum payload size (%d)' %
                    (payload_length, self._max_payload_size),
                    code=1009
                )

        if is_masked:
            masking_key = await self.request.recv(4)
            payload_data = await self.request.recv(payload_length)
            unmasked_data = bytes(
                data_byte ^ masking_key[i % 4] for i, data_byte in enumerate(
                    payload_data)
            )
        else:
            unmasked_data = await self.request.recv(payload_length)

        if opcode == 1 or opcode == 2 or opcode == 0:
            return unmasked_data

        # ping
        if opcode == 9 and payload_length < 126:
            await self.pong(unmasked_data)
            return b''

        # pong
        if opcode == 10 and payload_length < 126:
            return b''

        if opcode == 8:
            code = 1005

            if unmasked_data != b'':
                code = int.from_bytes(unmasked_data[:2], byteorder='big')

            raise WebSocketClientClosed(
                'connection closed (%d)' % code,
                code=code
            )

        raise WebSocketServerClosed(
            'unsupported opcode %x with payload length %d' %
            (opcode, payload_length),
            code=1008
        )

    async def receive(self):
        payload = bytearray()

        while True:
            coro = self.ping()
            timer = self.request.server.loop.call_at(
                self.request.server.loop.time() + self._receive_timeout,
                self.request.server.create_task, coro
            )

            try:
                frame = await self.recv()
            except TimeoutError as exc:
                raise WebSocketServerClosed('receive timeout',
                                            code=1000) from exc
            finally:
                timer.cancel()
                coro.close()

            if frame == b'':
                # got empty bytes (pong). continue and keep pinging
                continue

            payload.extend(frame)

            if len(payload) > self._max_payload_size:
                raise WebSocketServerClosed('maximum payload size exceeded',
                                            code=1009)

            if self.fin == 1:
                break

        if self.opcode == 1:
            return payload.decode('utf-8')

        return payload

    @staticmethod
    def create_frame(payload_data, fin=1, opcode=None, mask=False):
        if opcode is None:
            if isinstance(payload_data, str):
                opcode = 1
            else:
                opcode = 2

        if opcode == 1:
            payload_data = payload_data.encode('utf-8')

        first_byte = (fin << 7) | opcode
        payload_length = len(payload_data)

        if payload_length < 126:
            second_byte = payload_length
            payload_length_data = b''
        elif payload_length < 65536:
            second_byte = 126
            payload_length_data = payload_length.to_bytes(2, byteorder='big')
        else:
            second_byte = 127
            payload_length_data = payload_length.to_bytes(8, byteorder='big')

        if mask:
            second_byte |= (1 << 7)
            masking_key = os.urandom(4)

        frame_header = bytes([first_byte, second_byte]) + payload_length_data

        if mask:
            masked_payload_data = bytes(
                data_byte ^ masking_key[i % 4] for i, data_byte in enumerate(
                    payload_data)
            )
            payload_data = masking_key + masked_payload_data

        return frame_header + payload_data

    async def send(self, payload_data, fin=1, opcode=None):
        await self.response.send(
            __class__.create_frame(payload_data, fin=fin, opcode=opcode)
        )

    async def ping(self, data=b''):
        # ping only if this connection is still listed,
        # otherwise let the recv timeout drop it
        if self.request.server in self.request.server.globals.connections:
            await self.send(data, opcode=9)

    async def pong(self, data=b''):
        await self.send(data, opcode=10)

    async def close(self, code=1000):
        try:
            await self.send(code.to_bytes(2, byteorder='big'), opcode=8)
            self.response.close(keepalive=True)
        except RuntimeError:
            pass
