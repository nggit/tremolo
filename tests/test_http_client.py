#!/usr/bin/env python3

import multiprocessing as mp  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402

# makes imports relative from the repo directory
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from tests.http_server import (  # noqa: E402
    app,
    HTTP_HOST,
    HTTP_PORT,
    TEST_FILE
)
from tests.utils import (  # noqa: E402
    getcontents,
    chunked_detected,
    valid_chunked,
    create_dummy_data,
    create_chunked_body,
    create_dummy_body,
    create_multipart_body
)


class TestHTTPClient(unittest.TestCase):
    def setUp(self):
        try:
            sys.modules['__main__'].tests_run += 1
        except AttributeError:
            sys.modules['__main__'].tests_run = 1

        print('\r\033[2K{0:d}. {1:s}'.format(sys.modules['__main__'].tests_run,
                                             self.id()))

    def test_get_middleware_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='FOO',
                                   url='/',
                                   version='1.1')

        self.assertEqual(
            header[:header.find(b'\r\n')],
            b'HTTP/1.1 405 Method Not Allowed'
        )

    def test_get_ok_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/',
                                   version='1.0')

        self.assertEqual(
            header[:header.find(b'\r\n')],
            b'HTTP/1.0 503 Service Unavailable'
        )
        self.assertFalse(chunked_detected(header))
        self.assertTrue(header.find(b'\r\nX-Foo: bar') > -1 and
                        header.find(b'Set-Cookie: sess=www') > -1)

    def test_get_ok_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
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

    def test_post_form_ok_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='POST',
                                   url='/page/102?a=111&a=xyz&b=222',
                                   version='1.1',
                                   data='username=myuser&password=mypass')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload_ok_10(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 8192\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(8192))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload2_ok_10(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload2 HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 65536\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(65536))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload_ok_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(8192, chunk_size=4096))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload2_ok_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload2 HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(64 * 1024, chunk_size=4096))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload4_ok_11(self):
        boundary = b'----MultipartBoundary'
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload4 HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Type: multipart/form-data; boundary=%s\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT,
                    boundary,
                    create_chunked_body(create_multipart_body(
                        boundary,
                        file1=create_dummy_data(4096),
                        file2=create_dummy_data(65536))))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload3_payloadtoolarge_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload3 HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(2 * 1048576 + 16 * 1024,
                                                 chunk_size=16 * 1024))
        )

    def test_payloadtoolarge(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload3 HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Length: %d\r\n\r\n\x00' % (
                    HTTP_PORT, 2 * 1048576 + 16 * 1024)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 413 Payload Too Large')
        self.assertEqual(body, b'Payload Too Large')

    def test_continue(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload2 HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Expect: 100-continue\r\nContent-Length: %d\r\n\r\n%s' % (
                    HTTP_PORT, 64 * 1024, create_dummy_body(64 * 1024))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_expectationfailed(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload3 HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Expect: 100-continue\r\nContent-Length: %d\r\n\r\n\x00' % (
                    HTTP_PORT, 2 * 1048576 + 16 * 1024)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 417 Expectation Failed')
        self.assertEqual(body, b'Expectation Failed')

    def test_get_notfound_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_notfound_close_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.0',
                                   headers=['Connection: close'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_keepalive_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.0',
                                   headers=['Connection: keep-alive'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_close_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.1',
                                   headers=['Connection: close'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_notfound_keepalive_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.1',
                                   headers=['Connection: keep-alive'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_badrequest(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET HTTP/\r\nHost: localhost:%d\r\n\r\n' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')

    def test_badrequest_notarequest(self):
        data = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b' HTTP/\r\nHost: localhost:%d\r\n\r\n' % HTTP_PORT
        )

        self.assertEqual(data, (b'', b''))

    def test_badrequest(self):
        data = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET / HTTP/1.1\r\nHost: localhost:%d\r\n%s' % (
                    HTTP_PORT, b'\x00' * 8192)
        )

        self.assertEqual(data, (b'', b''))

    def test_headertoolarge(self):
        data = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET / HTTP/1.1\r\nHost: localhost:%d\r\n%s\r\n\r\n' % (
                    HTTP_PORT, b'\x00' * 8192)
        )

        self.assertEqual(data, (b'', b''))

    def test_requesttimeout(self):
        data = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 1,
            raw=b'GET / HTTP/1.1\r\nHost: localhost:%d\r\n' % (HTTP_PORT + 1)
        )

        self.assertEqual(data, (b'', b''))

    def test_download_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertEqual(header.find(b'\r\nAccept-Ranges:'), -1)
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(
            header.find(b'\r\nContent-Length: %d' %
                        os.stat(TEST_FILE).st_size) > 0
        )

    def test_download_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(header.find(b'\r\nAccept-Ranges: bytes') > 0)
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(
            header.find(b'\r\nContent-Length: %d' %
                        os.stat(TEST_FILE).st_size) > 0
        )

    def test_notmodified(self):
        mtime = os.path.getmtime(TEST_FILE)
        mdate = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(mtime))
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['If-Modified-Since: %s' % mdate])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 304 Not Modified')
        self.assertEqual(header.find(b'\r\nAccept-Ranges:'), -1)
        self.assertEqual(header.find(b'\r\nContent-Type:'), -1)
        self.assertEqual(header.find(b'\r\nContent-Length:'), -1)

    def test_range_ok(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=[
                                       'If-Range: xxx',
                                       'Range: bytes=15-21'
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(header.find(b'\r\nAccept-Ranges: bytes') > 0)
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(
            header.find(b'\r\nContent-Length: %d' %
                        os.stat(TEST_FILE).st_size) > 0
        )

    def test_download_range(self):
        mtime = os.path.getmtime(TEST_FILE)
        mdate = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(mtime))
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=[
                                       'If-Range: %s' % mdate,
                                       'Range: bytes=15-21'
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 206 Partial Content')
        self.assertEqual(body, b'python3')
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(header.find(b'\r\nContent-Length: 7') > 0)

    def test_download_range_start(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=[
                                       'Range: bytes=%d-' % (os.stat(
                                           TEST_FILE).st_size - 5)
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 206 Partial Content')
        self.assertEqual(body.strip(b'# \r\n'), b'END')
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(header.find(b'\r\nContent-Length: 5') > 0)

    def test_download_range_end(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=-5'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 206 Partial Content')
        self.assertEqual(body.strip(b'# \r\n'), b'END')
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(header.find(b'\r\nContent-Length: 5') > 0)

    def test_download_range_multipart(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-0, 2-2'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 206 Partial Content')
        self.assertEqual(header.find(b'\r\nContent-Length:'), -1)
        self.assertEqual(body.count(b'\r\nContent-Range: bytes 2-2/'), 2)
        self.assertEqual(body.count(b'\r\n------Boundary'), 3)
        self.assertEqual(body[-11:], b'--\r\n\r\n0\r\n\r\n')
        self.assertTrue(
            header.find(b'\r\nContent-Type: multipart/byteranges; '
                        b'boundary=----Boundary') > 0
        )
        self.assertTrue(valid_chunked(body))

    def test_badrange(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-2, 3'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad range')

    def test_badrange1(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=[
                                       'Range: bytes=0-1',
                                       'Range: bits=2-1'
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad range')

    def test_badrange2(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bits=2-1'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad range')

    def test_rangenotsatisfiable(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=-10000000'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertEqual(body, b'Range Not Satisfiable')

    def test_rangenotsatisfiable1(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=10000000-'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertEqual(body, b'Range Not Satisfiable')

    def test_rangenotsatisfiable2(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-1'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertEqual(body, b'Range Not Satisfiable')

    def test_rangenotsatisfiable3(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-10000000'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertEqual(body, b'Range Not Satisfiable')


if __name__ == '__main__':
    mp.set_start_method('spawn')

    p = mp.Process(
        target=app.run,
        kwargs=dict(host=HTTP_HOST, port=HTTP_PORT, debug=False)
    )

    try:
        p.start()
        unittest.main()
    finally:
        p.terminate()

# END
