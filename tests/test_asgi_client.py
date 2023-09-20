#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import tremolo  # noqa: E402

from tremolo.lib.websocket import WebSocket  # noqa: E402
from tests.http_server import TEST_FILE  # noqa: E402
from tests.asgi_server import app, ASGI_HOST, ASGI_PORT  # noqa: E402
from tests.utils import (  # noqa: E402
    getcontents,
    chunked_detected,
    create_dummy_body
)


class TestASGIClient(unittest.TestCase):
    def setUp(self):
        try:
            sys.modules['__main__'].tests_run += 1
        except AttributeError:
            sys.modules['__main__'].tests_run = 1

        print('\r\033[2K{0:d}. {1:s}'.format(sys.modules['__main__'].tests_run,
                                             self.id()))

    def test_get_ok_10(self):
        header, body = getcontents(host=ASGI_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/',
                                   version='1.0')

        self.assertEqual(
            header[:header.find(b'\r\n')],
            b'HTTP/1.0 200 OK'
        )
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertFalse(chunked_detected(header))
        self.assertTrue(b'Hello world!' in body)

    def test_get_ok_11(self):
        header, body = getcontents(host=ASGI_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/page/101?a=111&a=xyz&b=222',
                                   version='1.1',
                                   headers=[
                                       'Cookie: a=123',
                                       'Cookie: a=xxx, yyy'
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

    def test_post_upload_ok_10(self):
        header, body = getcontents(
            host=ASGI_HOST,
            port=ASGI_PORT,
            raw=b'POST /upload HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 8192\r\n\r\n%s' % (
                    ASGI_PORT, create_dummy_body(8192))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload2_ok_10(self):
        header, body = getcontents(
            host=ASGI_HOST,
            port=ASGI_PORT,
            raw=b'POST /upload2 HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 65536\r\n\r\n%s' % (
                    ASGI_PORT, create_dummy_body(65536))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload_ok_11(self):
        header, body = getcontents(
            host=ASGI_HOST,
            port=ASGI_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    ASGI_PORT, create_dummy_body(8192, chunk_size=4096))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

    def test_download_10(self):
        header, body = getcontents(host=ASGI_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/download',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(
            (b'\r\ncontent-length: %d' % os.stat(TEST_FILE).st_size) in header
        )

    def test_download_11(self):
        header, body = getcontents(host=ASGI_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/download',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(
            (b'\r\ncontent-length: %d' % os.stat(TEST_FILE).st_size) in header
        )

    def test_response_splitting(self):
        header, body = getcontents(host=ASGI_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/foo%0D%0Abar%3A%20baz',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 500 Internal Server Error')
        self.assertFalse(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(
            b'name or value cannot contain illegal characters' in body
        )

    def test_websocket(self):
        payload = getcontents(
            host=ASGI_HOST,
            port=ASGI_PORT,
            raw=b'GET /ws HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Upgrade: websocket\r\n'
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                b'Connection: upgrade\r\n\r\n%s' % (
                    ASGI_PORT,
                    WebSocket.create_frame(b'Hello, world!', mask=True))
        )
        self.assertEqual(payload, WebSocket.create_frame(b'Hello, world!'))


if __name__ == '__main__':
    mp.set_start_method('spawn')

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
