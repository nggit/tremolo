#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.http_server import (  # noqa: E402
    app,
    HTTP_HOST,
    HTTP_PORT,
    LIMIT_MEMORY
)
from tests.netizen import HTTPClient  # noqa: E402


class TestHTTPMalformed(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.client = HTTPClient(HTTP_HOST, HTTP_PORT, timeout=10, retries=10)
        self.client2 = HTTPClient(HTTP_HOST, HTTP_PORT + 2,
                                  timeout=10, retries=10)

    def test_get_doublehost_11(self):
        with self.client:
            self.client.sendall(
                b'GET /gethost HTTP/1.1\r\n'
                b'Host: localhost\r\n'
                b'Host: host.local\r\n\r\n'
            )

            response = self.client.end()

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')
            self.assertEqual(response.body(), b'Bad Request')

    def test_post_bad_chunked_encoding(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Transfer-Encoding: chunked'
            )

            self.client2.sendall(b'-1\r\n')

            self.assertEqual(response.body(), b'bad chunked encoding')
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_post_no_chunk_size(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Transfer-Encoding: chunked'
            )

            self.client2.sendall(b'X' * 65)

            self.assertEqual(
                response.body(), b'bad chunked encoding: no chunk size'
            )
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_post_invalid_chunk_terminator(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Transfer-Encoding: chunked'
            )

            self.client2.sendall(b'1\r\nA\rX')

            self.assertEqual(
                response.body(),
                b'bad chunked encoding: invalid chunk terminator'
            )
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_post_invalid_chunk_end(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Transfer-Encoding: chunked'
            )

            self.client2.sendall(b'0;\r\n\rX')

            self.assertEqual(
                response.body(),
                b'bad chunked encoding: invalid chunk terminator'
            )
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_get_badrequest(self):
        with self.client:
            response = self.client.send(b'GET HTTP/')

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_badrequest_notarequest(self):
        with self.client:
            response = self.client.send(b' HTTP/')

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')
            self.assertEqual(response.body(), b'bad request: not a request')

    def test_badrequest(self):
        with self.client:
            self.client.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\n')
            self.client.sendall(b'\x00' * 8192)

            response = self.client.end()

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')
            self.assertEqual(response.body(), b'bad request')

    def test_headertoolarge(self):
        with self.client:
            response = self.client.send(
                b'GET / HTTP/1.1',
                b'Host: ' + b'\x00' * 8192
            )

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')
            self.assertEqual(response.body(), b'request header too large')

    def test_content_length_and_transfer_encoding(self):
        with self.client:
            response = self.client.send(
                b'GET /upload HTTP/1.1',
                b'Content-Length: 5',
                b'Transfer-Encoding: chunked'
            )

            self.client.sendall(b'0\r\n\r\n')

            self.assertEqual(response.body(), b'ambiguous Content-Length')
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_double_content_length(self):
        with self.client:
            response = self.client.send(
                b'GET /upload HTTP/1.1',
                b'Content-Length: 1',
                b'Content-Length: 2'
            )

            self.client.sendall(b'AB')

            self.assertEqual(response.body(), b'ambiguous Content-Length')
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_empty_content_length(self):
        with self.client:
            response = self.client.send(
                b'GET /upload HTTP/1.1',
                b'Content-Length: '
            )

            self.assertEqual(response.body(), b'bad Content-Length')
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')


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
            'tests', pattern='test_http_malformed*.py'
        )
        unittest.TextTestRunner().run(suite)
    finally:
        if p.is_alive():
            os.kill(p.pid, signal.SIGINT)
            p.join()
