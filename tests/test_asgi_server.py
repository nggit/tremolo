#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tremolo  # noqa: E402

from tremolo.lib.websocket import WebSocket  # noqa: E402
from tests.http_server import TEST_FILE  # noqa: E402
from tests.asgi_server import app, ASGI_HOST, ASGI_PORT  # noqa: E402
from tests.netizen import HTTPClient  # noqa: E402
from tests.utils import create_dummy_body  # noqa: E402


class TestASGIServer(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.client = HTTPClient(ASGI_HOST, ASGI_PORT, timeout=10, retries=10)

    def test_app_exits_early(self):
        with self.client:
            response = self.client.send(b'GET /exit HTTP/1.0')

            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')
            self.assertEqual(response.body(), b'Internal Server Error')

    def test_double_start(self):
        with self.client:
            response = self.client.send(b'GET /start HTTP/1.0')

            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')
            self.assertEqual(response.body(), b'already started or accepted')

    def test_body_before_start(self):
        with self.client:
            response = self.client.send(b'GET /body HTTP/1.0')

            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')
            self.assertEqual(
                response.body(), b'has not been started or accepted'
            )

    def test_invalid_message_type(self):
        with self.client:
            response = self.client.send(b'GET /invalid HTTP/1.0')

            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')

    def test_get_ok_10(self):
        with self.client:
            response = self.client.send(b'GET / HTTP/1.0')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'Hello, World!')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )

    def test_get_ok_11(self):
        with self.client:
            response = self.client.send(
                b'GET /page/101?a=111&a=xyz&b=222 HTTP/1.1',
                b'Cookie: a=123',
                b'Cookie: a=xxx, yyy'
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')

    def test_post_upload_ok_10(self):
        with self.client:
            response = self.client.send(
                b'POST /upload HTTP/1.0',
                body=create_dummy_body(8192)
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')

    def test_post_upload2_ok_10(self):
        with self.client:
            response = self.client.send(
                b'POST /upload2 HTTP/1.0',
                body=create_dummy_body(65536)
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')

    def test_post_upload_ok_11(self):
        with self.client:
            self.client.send(
                b'POST /upload HTTP/1.1',
                b'Transfer-Encoding: chunked'
            )
            self.client.sendall(create_dummy_body(8192, chunk_size=4096))
            response = self.client.end()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')

    def test_download_10(self):
        with self.client:
            response = self.client.send(b'GET /download HTTP/1.0')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )
            self.assertEqual(
                response.headers[b'content-length'],
                [b'%d' % os.stat(TEST_FILE).st_size]
            )

    def test_download_11(self):
        with self.client:
            response = self.client.send(b'GET /download HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )
            self.assertEqual(
                response.headers[b'content-length'],
                [b'%d' % os.stat(TEST_FILE).st_size]
            )

    def test_sec_response_splitting(self):
        with self.client:
            response = self.client.send(b'GET /foo%0D%0Abar%3A%20baz HTTP/1.1')

            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')
            self.assertFalse(
                b'text/plain' in response.headers[b'content-type']
            )

    def test_websocket(self):
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
                WebSocket.create_frame(b'Hello, World!', mask=True)
            )
            self.client.sendall(WebSocket.create_frame(b'\x03\xe8', opcode=8))

            self.assertEqual(
                self.client.recv(15), WebSocket.create_frame(b'Hello, World!')
            )

    def test_websocket_close(self):
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

            self.client.sendall(WebSocket.create_frame(b'\x03\xe8', opcode=8))

            self.assertEqual(self.client.recv(4096), b'\x88\x02\x03\xe8')

    def test_websocket_close_before_accept(self):
        with self.client:
            response = self.client.send(
                b'GET /close HTTP/1.1',
                b'Upgrade: WebSocket',
                b'Connection: Upgrade',
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
                b'Sec-WebSocket-Version: 13'
            )

            self.assertEqual(response.status, 403)
            self.assertEqual(response.message, b'Forbidden')

    def test_websocket_invalid_opcode(self):
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
                WebSocket.create_frame(b'', mask=True, opcode=0xc)
            )
            self.client.sendall(WebSocket.create_frame(b'\x03\xe8', opcode=8))

            self.assertEqual(self.client.recv(4096), b'\x88\x02\x03\xf0')


if __name__ == '__main__':
    mp.set_start_method('spawn', force=True)

    p = mp.Process(
        target=tremolo.run,
        kwargs=dict(app=app, host=ASGI_HOST, port=ASGI_PORT, debug=False)
    )

    p.start()

    try:
        unittest.main()
    finally:
        if p.is_alive():
            os.kill(p.pid, signal.SIGINT)
            p.join()

# END
