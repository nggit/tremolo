#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo.lib.websocket import WebSocket  # noqa: E402
from tests.http_server import (  # noqa: E402
    app,
    HTTP_HOST,
    HTTP_PORT,
    LIMIT_MEMORY
)
from tests.netizen import HTTPClient  # noqa: E402


class TestHTTPWebSocket(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.client = HTTPClient(HTTP_HOST, HTTP_PORT, timeout=10, retries=10)

    def test_websocket_receive_text_short(self):
        with self.client:
            response = self.client.send(
                b'GET /ws?receive HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(
                WebSocket.create_frame('Hello, World!', mask=True)
            )

            self.assertEqual(self.client.recv(15), b'\x81\rHello, World!')

    def test_websocket_receive_binary_127(self):
        with self.client:
            response = self.client.send(
                b'GET /ws?receive HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(
                WebSocket.create_frame(b'i' * 127, mask=True, opcode=2)
            )

            self.assertEqual(self.client.recv(8), b'\x82~\x00\x7fiiii')

    def test_websocket_receive_binary_65536(self):
        with self.client:
            response = self.client.send(
                b'GET /ws?receive HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(
                WebSocket.create_frame(b'i' * 65536, mask=True, opcode=2)
            )

            self.assertEqual(
                self.client.recv(7), b'\x82\x7f\x00\x00\x00\x00\x00'
            )

    def test_websocket_receive_too_large(self):
        with self.client:
            response = self.client.send(
                b'GET /ws?receive HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(
                WebSocket.create_frame(b'i' * 81920, mask=True, opcode=2)
            )

            self.assertEqual(self.client.recv(4), b'\x88\x02\x03\xf1')

    def test_websocket_ping(self):
        with self.client:
            response = self.client.send(
                b'GET /ws?ping HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(
                WebSocket.create_frame(b'', mask=True, opcode=9)
            )

            self.assertEqual(self.client.recv(2), b'\x8a\x00')

    def test_websocket_close_server_initiated(self):
        with self.client:
            response = self.client.send(
                b'GET /ws?close HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.assertEqual(self.client.recv(4), b'\x88\x02\x03\xe8')
            self.client.sendall(WebSocket.create_frame(b'\x03\xe8', opcode=8))

    def test_websocket_close_reason(self):
        with self.client:
            response = self.client.send(
                b'GET /ws HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(
                WebSocket.create_frame(b'\x03\xe8CLOSE_NORMAL', opcode=8)
            )

            self.assertEqual(self.client.recv(4), b'\x88\x02\x03\xe8')

    def test_websocket_close_invalid_frame(self):
        with self.client:
            response = self.client.send(
                b'GET /ws HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(
                WebSocket.create_frame(b'', mask=True, opcode=0x0c)
            )

            self.assertEqual(self.client.recv(4), b'\x88\x02\x03\xf0')

    def test_websocket_continuation(self):
        payload = (WebSocket.create_frame(b'Hello', fin=0) +
                   WebSocket.create_frame(b', ', fin=0, opcode=0) +
                   WebSocket.create_frame(b'World', fin=0, opcode=0) +
                   WebSocket.create_frame(b'!', fin=1, opcode=0))

        with self.client:
            response = self.client.send(
                b'GET /ws HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(payload)

            self.assertEqual(self.client.recv(15), b'\x82\rHello, World!')

    def test_websocket_unexpected_start(self):
        payload = (WebSocket.create_frame(b'Hello', fin=0) +
                   WebSocket.create_frame(b'Hello', fin=0))

        with self.client:
            response = self.client.send(
                b'GET /ws HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(payload)

            self.assertEqual(self.client.recv(4096), b'\x88\x02\x03\xea')

    def test_websocket_unexpected_continuation(self):
        payload = WebSocket.create_frame(b'World', fin=0, opcode=0)

        with self.client:
            response = self.client.send(
                b'GET /ws HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(payload)

            self.assertEqual(self.client.recv(4096), b'\x88\x02\x03\xea')

    def test_websocket_max_payload(self):
        payload = (WebSocket.create_frame(b'Hello, World', fin=0) +
                   WebSocket.create_frame(b'!' * 65536, fin=0, opcode=0) +
                   WebSocket.create_frame(b'!' * 65536, fin=1, opcode=0))

        with self.client:
            response = self.client.send(
                b'GET /ws HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 101)
            self.assertEqual(response.message, b'Switching Protocols')

            self.client.sendall(payload)

            self.assertEqual(self.client.recv(4096), b'\x88\x02\x03\xf1')


if __name__ == '__main__':
    mp.set_start_method('spawn', force=True)

    p = mp.Process(
        target=app.run,
        kwargs=dict(host=HTTP_HOST,
                    port=HTTP_PORT,
                    limit_memory=LIMIT_MEMORY,
                    debug=False,
                    reload=True,
                    loop='asyncio.SelectorEventLoop',
                    client_max_body_size=1048576,  # 1MiB
                    ws_max_payload_size=73728)
    )

    p.start()

    try:
        suite = unittest.TestLoader().discover(
            'tests', pattern='test_http_websocket*.py'
        )
        unittest.TextTestRunner().run(suite)
    finally:
        if p.is_alive():
            os.kill(p.pid, signal.SIGINT)
            p.join()
