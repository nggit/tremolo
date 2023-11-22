#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import sys
import time
import unittest

# makes imports relative from the repo directory
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from tremolo.lib.websocket import WebSocket  # noqa: E402
from tests.http_server import (  # noqa: E402
    app,
    HTTP_HOST,
    HTTP_PORT,
    TEST_FILE
)
from tests.utils import (  # noqa: E402
    getcontents,
    chunked_detected,
    read_chunked,
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
            b'HTTP/1.0 503 Under Maintenance'
        )
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertFalse(chunked_detected(header))

        # these values are set by the request and response middleware
        self.assertTrue(b'\r\nX-Foo: baz' in header and
                        b'Set-Cookie: sess=www' in header)

    def test_get_ip_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/getip',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body)[-9:], b'127.0.0.1')

    def test_get_xip_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/getip',
                                   version='1.1',
                                   headers=[
                                       'X-Forwarded-For: 192.168.0.2, xxx',
                                       'X-Forwarded-For: 192.168.0.20'
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'192.168.0.2')

    def test_get_xip_empty_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/getip',
                                   version='1.1',
                                   headers=[
                                       'X-Forwarded-For:  '
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body)[-9:], b'127.0.0.1')

    def test_get_headerline_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET /getheaderline?foo HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Host: host.local\r\n\r\n' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body),
                         b'GET /getheaderline?foo HTTP/1.1')

    def test_get_doublehost_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET /gethost HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Host: host.local\r\n\r\n' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'localhost:%d' % HTTP_PORT)

    def test_get_query_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/getquery?a=111&a=xyz&b=222',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'a=111&b=222')

    def test_get_page_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/page/101',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'101')

    def test_get_cookies_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/getcookies',
                                   version='1.1',
                                   headers=[
                                       'Cookie: a=123',
                                       'Cookie: a=xxx, yyy'
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'a=123, a=xxx, yyy')

    def test_head_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='HEAD',
                                   url='/',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 503 Under Maintenance')
        self.assertTrue(b'\r\nContent-Length: ' in header)
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertFalse(b'\r\nTransfer-Encoding: chunked\r\n' in header)
        self.assertEqual(body, b'')

    def test_head_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='HEAD',
                                   url='/invalid',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 404 Not Found')
        self.assertFalse(b'\r\nContent-Length: ' in header)
        self.assertTrue(b'\r\nTransfer-Encoding: chunked\r\n' in header)
        self.assertEqual(body, b'')

    def test_get_lock_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/getlock',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'Lock was acquired!')

    def test_post_form_ok_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='POST',
                                   url='/submitform',
                                   version='1.1',
                                   data='username=myuser&password=mypass')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body),
                         b'username=myuser&password=mypass')

    def test_post_upload_ok_10(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload?size=-1 HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 8192\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(8192))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertTrue(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertFalse(chunked_detected(header))
        self.assertEqual(body, create_dummy_body(8192))

    def test_post_upload2_ok_10(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload?size=10 HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 65536\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(65536))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertTrue(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertFalse(chunked_detected(header))
        self.assertEqual(body, create_dummy_body(65536)[:10])

    def test_post_upload_ok_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(8192, chunk_size=4096))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertEqual(read_chunked(body), create_dummy_body(8192))

    def test_post_upload2_ok_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(65536, chunk_size=4096))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertEqual(read_chunked(body), create_dummy_body(65536))

    def test_post_upload_maxqueue(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload?maxqueue HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 8192\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(8192))
        )

        self.assertEqual(header, b'')
        self.assertEqual(body, b'')

    def test_post_upload_multipart_11(self):
        boundary = b'----MultipartBoundary'
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload/multipart HTTP/1.1\r\nHost: localhost:%d\r\n'
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
        self.assertTrue(b'\r\nContent-Type: text/csv' in header)
        self.assertEqual(
            read_chunked(body) if chunked_detected(header) else body,
            b'name,length,type,data\r\n'
            b'file1,4096,application/octet-stream,BEGINEND\r\n'
            b'file2,65536,application/octet-stream,BEGINEND\r\n'
        )

    def test_post_upload_payloadtoolarge_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(65536 + 16 * 1024,
                                                 chunk_size=16 * 1024))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertEqual(
            read_chunked(body) if chunked_detected(header) else body,
            False
        )

    def test_payloadtoolarge(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Length: %d\r\n\r\n\x00' % (
                    HTTP_PORT, 65536 + 16 * 1024)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 413 Payload Too Large')
        self.assertFalse(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertTrue(b'Payload Too Large' in body)

    def test_continue(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Expect: 100-continue\r\nContent-Length: %d\r\n\r\n%s' % (
                    HTTP_PORT, 65536, create_dummy_body(65536))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertEqual(read_chunked(body), create_dummy_body(65536))

    def test_expectationfailed(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Expect: 100-continue\r\nContent-Length: %d\r\n\r\n\x00' % (
                    HTTP_PORT, 2 * 1048576 + 16 * 1024)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 417 Expectation Failed')
        self.assertFalse(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertTrue(b'Expectation Failed' in body)

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

    def test_get_notfound_keepalive_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.1',
                                   headers=['Connection: keep-alive'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 404 Not Found')

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
        for _ in range(10):
            try:
                data = getcontents(
                    host=HTTP_HOST,
                    port=HTTP_PORT + 1,
                    raw=b'GET / HTTP/1.1\r\n'
                        b'Host: localhost:%d\r\n' % (HTTP_PORT + 1)
                )
                break
            except ConnectionResetError:
                continue

        self.assertEqual(data, (b'', b''))

    def test_recvtimeout(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 1,
            raw=b'GET /timeouts?recv HTTP/1.1\r\nHost: localhost:%d\r\n\r\n' %
                (HTTP_PORT + 1)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 408 Request Timeout')
        self.assertEqual(body, b'Request Timeout')

    def test_handlertimeout(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'GET /timeouts?handler HTTP/1.1\r\n'
                b'Host: localhost:%d\r\n\r\n' % (HTTP_PORT + 2)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 500 Internal Server Error')
        self.assertEqual(body, b'Internal Server Error')

    def test_download_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(b'\r\nAccept-Ranges:' in header)
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(
            (b'\r\nContent-Length: %d' % os.stat(TEST_FILE).st_size) in header
        )

    def test_download_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(b'\r\nAccept-Ranges: bytes' in header)
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(
            (b'\r\nContent-Length: %d' % os.stat(TEST_FILE).st_size) in header
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
        self.assertFalse(b'\r\nAccept-Ranges:' in header)
        self.assertFalse(b'\r\nContent-Type:' in header)
        self.assertFalse(b'\r\nContent-Length:' in header)

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
        self.assertTrue(b'\r\nAccept-Ranges: bytes' in header)
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(
            (b'\r\nContent-Length: %d' % os.stat(TEST_FILE).st_size) in header
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
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(b'\r\nContent-Length: 7' in header)

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
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(b'\r\nContent-Length: 5' in header)

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
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertTrue(b'\r\nContent-Length: 5' in header)

    def test_download_range_multipart(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-0, 2-2'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 206 Partial Content')
        self.assertFalse(b'\r\nContent-Length:' in header)
        self.assertEqual(body.count(b'\r\nContent-Range: bytes 2-2/'), 2)
        self.assertEqual(body.count(b'\r\n------Boundary'), 3)
        self.assertEqual(body[-11:], b'--\r\n\r\n0\r\n\r\n')
        self.assertTrue(
            (b'\r\nContent-Type: multipart/byteranges; '
             b'boundary=----Boundary') in header
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
        self.assertTrue(b'bad range' in body)

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
        self.assertTrue(b'bad range' in body)

    def test_badrange2(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bits=2-1'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertTrue(b'bad range' in body)

    def test_rangenotsatisfiable(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=-10000000'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertTrue(b'Range Not Satisfiable' in body)

    def test_rangenotsatisfiable1(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=10000000-'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertTrue(b'Range Not Satisfiable' in body)

    def test_rangenotsatisfiable2(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-1'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertTrue(b'Range Not Satisfiable' in body)

    def test_rangenotsatisfiable3(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT + 2,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-10000000'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertTrue(b'Range Not Satisfiable' in body)

    def test_websocket(self):
        for query, data_in, data_out, opcode, in (
                (b'receive', 'Hello, world!', b'\x81\rHello, world!', None),
                (b'receive', b'i' * 127, b'\x82~\x00\x7fiiii', 2),
                (b'receive', b'i' * 65536, b'\x82\x7f\x00\x00\x00\x00\x00', 2),
                (b'receive', b'i' * 81920, b'\x88\x02\x03\xf1', 2),
                (b'ping', b'', b'\x89\x00', 9),
                (b'close', b'\x03\xe8', b'\x88\x02\x03\xe8', 8),
                (b'', b'\x03\xe8CLOSE_NORMAL', b'', 8),
                (b'', b'', b'\x88\x02\x03\xf0', 0xc)):
            payload = getcontents(
                host=HTTP_HOST,
                port=HTTP_PORT,
                raw=b'GET /ws?%s HTTP/1.1\r\nHost: localhost:%d\r\n'
                    b'Upgrade: websocket\r\n'
                    b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                    b'Connection: upgrade\r\n\r\n%s' % (
                        query,
                        HTTP_PORT,
                        WebSocket.create_frame(data_in,
                                               mask=(opcode != 8),
                                               opcode=opcode))
            )

            self.assertEqual(payload[:7], data_out[:7])

    def test_reload(self):
        header, body1 = getcontents(host=HTTP_HOST,
                                    port=HTTP_PORT,
                                    method='GET',
                                    url='/reload?%f' % time.time(),
                                    version='1.0')

        self.assertFalse(body1 == b'')

        for _ in range(10):
            time.sleep(1)

            try:
                header, body2 = getcontents(host=HTTP_HOST,
                                            port=HTTP_PORT,
                                            method='GET',
                                            url='/reload',
                                            version='1.0')
            except ConnectionResetError:
                continue

            self.assertFalse(body2 == b'')

            if body2 != body1:
                break

        self.assertFalse(body2 == body1)


if __name__ == '__main__':
    mp.set_start_method('spawn')

    p = mp.Process(
        target=app.run,
        kwargs=dict(host=HTTP_HOST,
                    port=HTTP_PORT,
                    debug=False,
                    reload=True,
                    client_max_body_size=73728)
    )

    p.start()

    try:
        unittest.main()
    finally:
        if p.is_alive():
            os.kill(p.pid, signal.SIGINT)
            p.join()

# END
