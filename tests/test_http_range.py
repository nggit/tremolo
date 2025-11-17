#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import sys
import time
import unittest

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.http_server import (  # noqa: E402
    app,
    HTTP_HOST,
    HTTP_PORT,
    TEST_FILE,
    LIMIT_MEMORY
)
from tests.netizen import HTTPClient  # noqa: E402


class TestHTTPRange(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.client = HTTPClient(HTTP_HOST, HTTP_PORT, timeout=10, retries=10)
        self.client2 = HTTPClient(HTTP_HOST, HTTP_PORT + 2,
                                  timeout=10, retries=10)

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
            self.assertFalse(b'accept-ranges' in response.headers)

    def test_download_11(self):
        with self.client2:
            response = self.client2.send(b'GET /download?executor HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )
            self.assertEqual(
                response.headers[b'content-length'],
                [b'%d' % os.stat(TEST_FILE).st_size]
            )
            self.assertEqual(response.headers[b'accept-ranges'], [b'bytes'])

    def test_notmodified(self):
        mtime = os.path.getmtime(TEST_FILE)
        mdate = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(mtime))

        with self.client:
            response = self.client.send(
                b'GET /download HTTP/1.1',
                b'If-Modified-Since: %s' % mdate.encode('latin-1')
            )

            self.assertEqual(response.status, 304)
            self.assertEqual(response.message, b'Not Modified')
            self.assertFalse(b'content-type' in response.headers)
            self.assertFalse(b'content-length' in response.headers)
            self.assertFalse(b'accept-ranges' in response.headers)

    def test_range_ok(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'If-Range: xxx',
                b'Range: bytes=15-21'
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )
            self.assertEqual(
                response.headers[b'content-length'],
                [b'%d' % os.stat(TEST_FILE).st_size]
            )
            self.assertEqual(response.headers[b'accept-ranges'], [b'bytes'])

    def test_download_range(self):
        mtime = os.path.getmtime(TEST_FILE)
        mdate = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(mtime))

        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'If-Range: %s' % mdate.encode('latin-1'),
                b'Range: bytes=15-21'
            )

            self.assertEqual(response.status, 206)
            self.assertEqual(response.message, b'Partial Content')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )
            self.assertEqual(response.headers[b'content-length'], [b'7'])
            self.assertEqual(response.body(), b'python3')

    def test_download_range_start(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=%d-' % (os.stat(TEST_FILE).st_size - 5)
            )

            self.assertEqual(response.status, 206)
            self.assertEqual(response.message, b'Partial Content')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )
            self.assertEqual(response.headers[b'content-length'], [b'5'])
            self.assertEqual(response.body().strip(b'# \r\n'), b'END')

    def test_download_range_end(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=-5'
            )

            self.assertEqual(response.status, 206)
            self.assertEqual(response.message, b'Partial Content')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )
            self.assertEqual(response.headers[b'content-length'], [b'5'])
            self.assertEqual(response.body().strip(b'# \r\n'), b'END')

    def test_download_range_multipart(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=2-0, 2-2'
            )
            body = response.body()

            self.assertEqual(response.status, 206)
            self.assertEqual(response.message, b'Partial Content')
            self.assertEqual(body.count(b'\r\nContent-Range: bytes 2-2/'), 2)
            self.assertEqual(body.count(b'------Boundary'), 3)
            self.assertEqual(body[-4:], b'--\r\n')
            self.assertEqual(
                response.headers[b'content-type'][0][:43],
                b'multipart/byteranges; boundary=----Boundary'
            )
            self.assertFalse(b'content-length' in response.headers)

    def test_badrange(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=2-2, 3'
            )

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')
            self.assertEqual(response.body(), b'bad range')

    def test_badrange1(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=0-1',
                b'Range: bits=2-1'
            )

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')
            self.assertEqual(response.body(), b'bad range')

    def test_badrange2(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bits=2-1'
            )

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')
            self.assertEqual(response.body(), b'bad range')

    def test_rangenotsatisfiable(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=-10000000'
            )

            self.assertEqual(response.status, 416)
            self.assertEqual(response.message, b'Range Not Satisfiable')
            self.assertEqual(response.body(), b'Range Not Satisfiable')

    def test_rangenotsatisfiable1(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=10000000-'
            )

            self.assertEqual(response.status, 416)
            self.assertEqual(response.message, b'Range Not Satisfiable')
            self.assertEqual(response.body(), b'Range Not Satisfiable')

    def test_rangenotsatisfiable2(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=2-1'
            )

            self.assertEqual(response.status, 416)
            self.assertEqual(response.message, b'Range Not Satisfiable')
            self.assertEqual(response.body(), b'Range Not Satisfiable')

    def test_rangenotsatisfiable3(self):
        with self.client2:
            response = self.client2.send(
                b'GET /download HTTP/1.1',
                b'Range: bytes=2-10000000'
            )

            self.assertEqual(response.status, 416)
            self.assertEqual(response.message, b'Range Not Satisfiable')
            self.assertEqual(response.body(), b'Range Not Satisfiable')


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
            'tests', pattern='test_http_range*.py'
        )
        unittest.TextTestRunner().run(suite)
    finally:
        if p.is_alive():
            os.kill(p.pid, signal.SIGINT)
            p.join()
