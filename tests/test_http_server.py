#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import sys
import time
import unittest

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo.lib.websocket import WebSocket  # noqa: E402
from tests.http_server import (  # noqa: E402
    app,
    HTTP_HOST,
    HTTP_PORT,
    TEST_FILE,
    LIMIT_MEMORY
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


class TestHTTPServer(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

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
        self.assertTrue(b'\r\nContent-Type: text/plain' in header)
        self.assertFalse(chunked_detected(header))
        self.assertEqual(body, b'Under Maintenance')

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
                b'\r\n\r\n' % HTTP_PORT
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

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'Bad Request')

    def test_get_query_11(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/getquery?a=111&a=xyz&b=222',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'a=111&b=222&')

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
        self.assertEqual(read_chunked(body), b'a=123, yyy, a=xxx')

    def test_head_10(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='HEAD',
                                   url='/',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 503 Service Unavailable')
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

    def test_limit_memory(self):
        _, body = getcontents(host=HTTP_HOST,
                              port=HTTP_PORT,
                              method='GET',
                              url='/triggermemoryleak',
                              version='1.0')

        self.assertEqual(body, b'')

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

    def test_post_form_invalid_content_type(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /submitform HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Type: application/json\r\n\r\n' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'invalid Content-Type')

    def test_post_form_limit(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='POST',
                                   url='/submitform',
                                   version='1.1',
                                   data='d' * 8193)

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 500 Internal Server Error')
        self.assertEqual(body, b'form size limit reached')

    def test_post_upload_ok_10(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload?size=-1 HTTP/1.0\r\nHost: localhost:%d\r\n'
                b'Content-Length: 8192\r\n\r\n%sX' % (
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
            port=HTTP_PORT + 2,
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
            port=HTTP_PORT + 2,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%sX' % (
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
            port=HTTP_PORT + 2,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(65536, chunk_size=4096))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(
            b'\r\nContent-Type: application/octet-stream' in header
        )
        self.assertEqual(read_chunked(body), create_dummy_body(65536))

    def test_post_bad_chunked_encoding(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n-1\r\n' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad chunked encoding')

    def test_post_no_chunk_size(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' %
                (HTTP_PORT, b'X' * 65)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad chunked encoding: no chunk size')

    def test_post_invalid_chunk_terminator(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n1\r\nA\rX' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body,
                         b'bad chunked encoding: invalid chunk terminator')

    def test_post_invalid_chunk_end(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n0;\r\n\rX' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body,
                         b'bad chunked encoding: invalid chunk terminator')

    def test_post_upload_maxqueue(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
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
            port=HTTP_PORT + 2,
            raw=b'POST /upload/multipart HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Type: multipart/form-data; boundary=%s\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT,
                    boundary,
                    create_chunked_body(create_multipart_body(
                        boundary,
                        file1=create_dummy_data(4096),
                        file2=create_dummy_data(524288))))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(b'\r\nContent-Type: text/csv' in header)
        self.assertEqual(
            read_chunked(body) if chunked_detected(header) else body,
            b'name,type,data\r\n'
            b'file1,application/octet-stream,BEGINEND\r\n'
            b'file2,application/octet-stream,BEGIN---\r\n'
            b'file2,application/octet-stream,-----END\r\n'
        )

    def test_post_upload_multipart_form(self):
        boundary = b'----MultipartBoundary'
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload/multipart/form HTTP/1.1\r\n'
                b'Host: localhost:%d\r\n'
                b'Content-Type: multipart/form-data; boundary=%s\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT,
                    boundary,
                    create_chunked_body(create_multipart_body(
                        boundary,
                        text=b'Hello, World!',
                        file=create_dummy_data(262144))))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'BEGINHello, World!END')

    def test_post_upload_multipart_form_fragmented(self):
        boundary = b'----MultipartBoundary'
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload/multipart/form HTTP/1.1\r\n'
                b'Host: localhost:%d\r\n'
                b'Content-Type: multipart/form-data; boundary=%s\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT,
                    boundary,
                    create_chunked_body(create_multipart_body(
                        boundary,
                        text=b'Hello, World!',
                        file=create_dummy_data(524288))))
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 500 Internal Server Error')

    def test_post_upload_payloadtoolarge_11(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Transfer-Encoding: chunked\r\n\r\n%s' % (
                    HTTP_PORT, create_dummy_body(1048576 + 8192,
                                                 chunk_size=16384))
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(
            b'\r\nContent-Type: application/octet-stream' in header
        )

    def test_payloadtoolarge(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 2,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Length: %d\r\n\r\n\x00' % (
                    HTTP_PORT, 1048576 + 8192)
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
            port=HTTP_PORT + 2,
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
                    HTTP_PORT, 2 * 1048576 + 16384)
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
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b' HTTP/\r\nHost: localhost:%d\r\n\r\n' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 400 Bad Request')
        self.assertEqual(body, b'bad request: not a request')

    def test_badrequest(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET / HTTP/1.1\r\nHost: localhost:%d\r\n%s' % (
                    HTTP_PORT, b'\x00' * 8192)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 400 Bad Request')
        self.assertEqual(body, b'bad request')

    def test_headertoolarge(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET / HTTP/1.1\r\nHost: localhost:%d\r\n%s\r\n\r\n' % (
                    HTTP_PORT, b'\x00' * 8192)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 400 Bad Request')
        self.assertEqual(body, b'request header too large')

    def test_sec_content_length_and_transfer_encoding(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Length: 5r\n'
                b'Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'Bad Request')

    def test_sec_double_content_length(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Length: 1\r\nContent-Length: 2\r\n\r\nAB' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad Content-Length')

    def test_sec_empty_content_length(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'POST /upload HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Content-Length: \r\n\r\n' % HTTP_PORT
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad Content-Length')

    def test_requesttimeout(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 1,
            raw=b'GET / HTTP/1.1\r\n'
                b'Host: localhost:%d\r\n' % (HTTP_PORT + 1)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 408 Request Timeout')
        self.assertEqual(body, b'request timeout after 1s')

    def test_recv_timeout(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 1,
            raw=b'GET /timeouts?recv HTTP/1.1\r\nHost: localhost:%d\r\n\r\n' %
                (HTTP_PORT + 1)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 408 Request Timeout')
        self.assertEqual(body, b'recv timeout')

    def test_handler_timeout(self):
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 1,
            raw=b'GET /timeouts?handler HTTP/1.1\r\n'
                b'Host: localhost:%d\r\n\r\n' % (HTTP_PORT + 1)
        )

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 500 Internal Server Error')
        self.assertEqual(body, b'Internal Server Error')

    def test_close_timeout(self):
        data = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT + 1,
            raw=b'GET /timeouts?close HTTP/1.1\r\n'
                b'Host: localhost:%d\r\n\r\n' % (HTTP_PORT + 1)
        )

        self.assertEqual(data, (b'', b''))

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
                                   url='/download?executor',
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
                (b'ping', b'', b'\x8a\x00', 9),
                (b'close', b'\x03\xe8', b'\x88\x02\x03\xe8', 8),
                (b'', b'\x03\xe8CLOSE_NORMAL', b'\x88\x02\x03\xe8', 8),
                (b'', b'', b'\x88\x02\x03\xf0', 0xc)):
            header, body = getcontents(
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

            self.assertEqual(body[:7], data_out[:7])

    def test_websocket_continuation(self):
        payload = (WebSocket.create_frame(b'Hello', fin=0) +
                   WebSocket.create_frame(b', ', fin=0, opcode=0) +
                   WebSocket.create_frame(b'World', fin=0, opcode=0) +
                   WebSocket.create_frame(b'!', fin=1, opcode=0))
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET /ws HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Upgrade: websocket\r\n'
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                b'Connection: upgrade\r\n\r\n%s' % (HTTP_PORT, payload)
        )

        self.assertEqual(body, b'\x82\rHello, World!')

    def test_websocket_unexpected_start(self):
        payload = (WebSocket.create_frame(b'Hello', fin=0) +
                   WebSocket.create_frame(b'Hello', fin=0))
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET /ws HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Upgrade: websocket\r\n'
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                b'Connection: upgrade\r\n\r\n%s' % (HTTP_PORT, payload)
        )

        self.assertEqual(body, b'\x88\x02\x03\xea')

    def test_websocket_unexpected_continuation(self):
        payload = WebSocket.create_frame(b'World', fin=0, opcode=0)
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET /ws HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Upgrade: websocket\r\n'
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                b'Connection: upgrade\r\n\r\n%s' % (HTTP_PORT, payload)
        )

        self.assertEqual(body, b'\x88\x02\x03\xea')

    def test_websocket_max_payload(self):
        payload = (WebSocket.create_frame(b'Hello, World', fin=0) +
                   WebSocket.create_frame(b'!' * 65536, fin=0, opcode=0) +
                   WebSocket.create_frame(b'!' * 65536, fin=1, opcode=0))
        header, body = getcontents(
            host=HTTP_HOST,
            port=HTTP_PORT,
            raw=b'GET /ws HTTP/1.1\r\nHost: localhost:%d\r\n'
                b'Upgrade: websocket\r\n'
                b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                b'Connection: upgrade\r\n\r\n%s' % (HTTP_PORT, payload)
        )

        self.assertEqual(body, b'\x88\x02\x03\xf1')

    def test_sse(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/sse',
                                   version='1.1')
        body = read_chunked(body)

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(b'\r\nContent-Type: text/event-stream' in header)
        self.assertTrue(b'\r\nCache-Control: no-cache' in header)
        self.assertTrue(b'data: Hel\ndata: lo\nevent: hello\n\n' in body)
        self.assertTrue(b'data: Wor\nid: foo\n\n' in body)
        self.assertTrue(b'data: ld!\nretry: 10000\n\n' in body)

    def test_sse_error(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/sse?error',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 500 Internal Server Error')

    def test_reload(self):
        if sys.platform != 'linux':
            return

        header, body1 = getcontents(host=HTTP_HOST,
                                    port=HTTP_PORT,
                                    method='GET',
                                    url='/reload?%f' % time.time(),
                                    version='1.0')

        self.assertFalse(body1 == b'')
        body2 = body1

        for _ in range(10):
            time.sleep(1)

            header, body2 = getcontents(host=HTTP_HOST,
                                        port=HTTP_PORT,
                                        method='GET',
                                        url='/reload',
                                        version='1.0')

            self.assertFalse(body2 == b'')

            if body2 != body1:
                break

        self.assertFalse(body2 == body1)

    def test_mount_subsub_with_middleware(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/sub/subsub/mount/',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'/sub/subsub')

    def test_mount_sub_no_middleware(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/sub/whatevermount',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'/')

    def test_class_get(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='GET',
                                   url='/resource',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertEqual(read_chunked(body), b'Hello, World!')

    def test_class_post_methodnotallowed(self):
        header, body = getcontents(host=HTTP_HOST,
                                   port=HTTP_PORT,
                                   method='PUT',
                                   url='/resource',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 405 Method Not Allowed')
        self.assertTrue(b'\r\nAllow: GET' in header)


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
        unittest.main()
    finally:
        if p.is_alive():
            os.kill(p.pid, signal.SIGINT)
            p.join()

# END
