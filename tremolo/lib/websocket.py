# Copyright (c) 2023 nggit

import base64
import hashlib
import os

from .http_exception import WebSocketException


class WebSocket:
    def __init__(self, request, response):
        self.request = request
        self.response = response
        self.protocol = request.protocol

    async def accept(self):
        magic_string = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
        sha1_hash = hashlib.sha1(self.request.headers[b'sec-websocket-key'] +
                                 magic_string).digest()
        accept_key = base64.b64encode(sha1_hash)

        self.response.set_status(101, b'Switching Protocols')
        self.response.append_header(
            b'Upgrade: websocket\r\n'
            b'Sec-WebSocket-Accept: %s\r\n' % accept_key
        )
        await self.response.write(None)

    async def recv(self):
        first_byte, second_byte = await self.request.recv(2)
        # we don't use FIN
        # fin = (first_byte & 0x80) >> 7
        opcode = first_byte & 0x0f
        is_masked = (second_byte & 0x80) >> 7
        payload_length = second_byte & 0x7f

        if payload_length == 126:
            payload_length = int.from_bytes(await self.request.recv(2),
                                            byteorder='big')
        elif payload_length == 127:
            payload_length = int.from_bytes(await self.request.recv(8),
                                            byteorder='big')

            if payload_length > self.protocol.options['client_max_body_size']:
                raise WebSocketException(
                    '{:d} exceeds maximum payload size ({:d})'
                    .format(
                        payload_length,
                        self.protocol.options['client_max_body_size'])
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

        if opcode == 1:
            return unmasked_data.decode('utf-8')

        if opcode == 2:
            return unmasked_data

        # ping
        if opcode == 9 and payload_length < 126:
            await self.send(unmasked_data, opcode=10)
            return b''

        # pong
        if opcode == 10 and payload_length < 126:
            return b''

        if opcode == 8:
            code = 1005

            if unmasked_data != b'':
                code = int.from_bytes(unmasked_data[:2], byteorder='big')

            raise WebSocketException(
                'connection closed ({:d})'.format(code),
                code=code
            )

        raise WebSocketException(
            'unsupported opcode {:x} with payload length {:d}'
            .format(opcode, payload_length)
        )

    async def receive(self):
        payload = b''

        while payload == b'':
            # got empty bytes (pong)
            # ping until non-empty bytes received
            timer = self.protocol.loop.call_at(
                self.protocol.loop.time() +
                self.protocol.options['keepalive_timeout'] / 2,
                self._ping
            )

            try:
                payload = await self.recv()
            finally:
                timer.cancel()

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

    def _ping(self):
        return self.protocol.loop.create_task(self.ping())

    async def ping(self):
        await self.send(b'', opcode=9)

    async def close(self, code=1000):
        await self.send(code.to_bytes(2, byteorder='big'), opcode=8)