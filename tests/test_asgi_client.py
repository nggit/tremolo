#!/usr/bin/env python3

import multiprocessing as mp
import os
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import tremolo  # noqa: E402

from tests.http_server import HTTP_HOST, TEST_FILE  # noqa: E402
from tests.asgi_server import app, ASGI_PORT  # noqa: E402
from tests.utils import (  # noqa: E402
    getcontents,
    chunked_detected,
    valid_chunked,
    create_dummy_body
)


class TestHTTPClient(unittest.TestCase):
    def setUp(self):
        try:
            sys.modules['__main__'].tests_run += 1
        except AttributeError:
            sys.modules['__main__'].tests_run = 1

        print('\r\033[2K{0:d}. {1:s}'.format(sys.modules['__main__'].tests_run,
                                             self.id()))

    def test_get_ok_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/',
                                   version='1.0')

        self.assertEqual(
            header[:header.find(b'\r\n')],
            b'HTTP/1.0 200 OK'
        )
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertFalse(chunked_detected(header))
        self.assertEqual(body, b'Hello world!')

    def test_get_ok_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/page/101?a=111&a=xyz&b=222',
                                   version='1.1',
                                   headers=[
                                       'Cookie: a=123',
                                       'Cookie: a=xxx, yyy'
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload_ok_10(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=ASGI_PORT,
            raw=b'POST /upload HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 8192\r\n\r\n%s' % (
                    ASGI_PORT, create_dummy_body(8192))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload2_ok_10(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=ASGI_PORT,
            raw=b'POST /upload2 HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 65536\r\n\r\n%s' % (
                    ASGI_PORT, create_dummy_body(65536))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload_ok_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=ASGI_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    ASGI_PORT, create_dummy_body(8192, chunk_size=4096))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

    def test_download_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/download',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(
            header.find(b'\r\ncontent-length: %d' %
                        os.stat(TEST_FILE).st_size) > 0
        )

    def test_download_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=ASGI_PORT,
                                   method='GET',
                                   url='/download',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(
            header.find(b'\r\ncontent-length: %d' %
                        os.stat(TEST_FILE).st_size) > 0
        )


if __name__ == '__main__':
    mp.set_start_method('spawn')

    p = mp.Process(
        target=tremolo.run,
        kwargs=dict(app=app, host=HTTP_HOST, port=ASGI_PORT, debug=False)
    )

    try:
        p.start()
        unittest.main()
    finally:
        p.terminate()

# END
