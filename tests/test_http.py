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
    LIMIT_MEMORY
)
from tests.netizen import HTTPClient  # noqa: E402
from tests.utils import (  # noqa: E402
    create_dummy_data,
    create_chunked_body,
    create_dummy_body,
    create_multipart_body
)


class TestHTTP(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.client = HTTPClient(HTTP_HOST, HTTP_PORT, timeout=10, retries=10)
        self.client1 = HTTPClient(HTTP_HOST, HTTP_PORT + 1,
                                  timeout=10, retries=10)
        self.client2 = HTTPClient(HTTP_HOST, HTTP_PORT + 2,
                                  timeout=10, retries=10)

    def test_get_middleware_11(self):
        with self.client:
            response = self.client.send(b'FOO / HTTP/1.1')

            self.assertEqual(response.header.version, b'HTTP/1.1')
            self.assertEqual(response.status, 405)
            self.assertEqual(response.message, b'Method Not Allowed')

    def test_get_ok_10(self):
        with self.client:
            response = self.client.send(b'GET / HTTP/1.0')

            self.assertEqual(response.header.version, b'HTTP/1.0')
            self.assertEqual(response.status, 503)
            self.assertEqual(response.message, b'Service Unavailable')
            self.assertEqual(response.body(), b'Under Maintenance')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/plain']
            )

            # these values are set by the request and response middleware
            self.assertEqual(response.headers[b'x-foo'], [b'baz'])
            self.assertEqual(
                response.headers[b'set-cookie'][0][:8], b'sess=www'
            )

    def test_get_ip_11(self):
        with self.client:
            response = self.client.send(b'GET /getip HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'127.0.0.1')

    def test_get_xip_11(self):
        with self.client:
            response = self.client.send(
                b'GET /getip HTTP/1.1',
                b'X-Forwarded-For: 192.168.0.2, xxx',
                b'X-Forwarded-For: 192.168.0.20'
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'192.168.0.2')

    def test_get_xip_empty_11(self):
        with self.client:
            response = self.client.send(
                b'GET /getip HTTP/1.1',
                b'X-Forwarded-For: ',
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'127.0.0.1')

    def test_get_headerline_11(self):
        with self.client:
            response = self.client.send(b'GET /getheaderline?foo HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.body(), b'GET /getheaderline?foo HTTP/1.1'
            )

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

    def test_get_query_11(self):
        with self.client:
            response = self.client.send(
                b'GET /getquery?a=111&a=xyz&b=222 HTTP/1.1'
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'a=111&b=222&')

    def test_get_page_11(self):
        with self.client:
            response = self.client.send(b'GET /page/101 HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'101')

    def test_get_cookies_11(self):
        with self.client:
            response = self.client.send(
                b'GET /getcookies HTTP/1.1',
                b'Cookie: a=123',
                b'Cookie: a=xxx, yyy'
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'a=123, yyy, a=xxx')

    def test_head_10(self):
        with self.client:
            response = self.client.send(b'HEAD / HTTP/1.0')

            self.assertEqual(response.header.version, b'HTTP/1.0')
            self.assertEqual(response.status, 503)
            self.assertEqual(response.message, b'Service Unavailable')
            self.assertEqual(response.body(), b'')

            self.assertTrue(b'content-length' in response.headers)
            self.assertFalse(b'transfer-encoding' in response.headers)

    def test_head_11(self):
        with self.client:
            response = self.client.send(b'HEAD /invalid HTTP/1.1')

            self.assertEqual(response.header.version, b'HTTP/1.1')
            self.assertEqual(response.status, 404)
            self.assertEqual(response.message, b'Not Found')
            self.assertEqual(response.body(), b'')

    def test_get_lock_11(self):
        with self.client:
            response = self.client.send(b'GET /getlock HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'Lock was acquired!')

    def test_limit_memory(self):
        with self.client:
            response = self.client.send(b'GET /triggermemoryleak HTTP/1.0')

            self.assertEqual(response.body(), b'')

    def test_post_form_ok_11(self):
        with self.client:
            response = self.client.send(
                b'POST /submitform HTTP/1.1',
                body=b'username=myuser&password=mypass'
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.body(), b'username=myuser&password=mypass'
            )

    def test_post_form_invalid_content_type(self):
        with self.client:
            response = self.client.send(
                b'POST /submitform HTTP/1.1',
                b'Content-Type: application/json'
            )

            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')
            self.assertEqual(response.body(), b'invalid Content-Type')

    def test_post_form_limit(self):
        with self.client:
            response = self.client.send(
                b'POST /submitform HTTP/1.1',
                body=b'd' * 8193
            )

            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')
            self.assertEqual(response.body(), b'form size limit reached')

    def test_post_upload_ok_10(self):
        with self.client2:
            body = create_dummy_body(8192)
            response = self.client2.send(
                b'POST /upload?size=-1 HTTP/1.0',
                b'Content-Length: %d' % len(body)
            )

            self.client2.sendall(body)
            self.client2.sendall(b'X')

            self.assertEqual(response.body(), body)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'],
                [b'application/octet-stream']
            )
            self.assertFalse(b'transfer-encoding' in response.headers)

    def test_post_upload2_ok_10(self):
        with self.client2:
            body = create_dummy_body(65536)
            response = self.client2.send(
                b'POST /upload?size=10 HTTP/1.0',
                body=body
            )

            self.assertEqual(response.body(), body[:10])
            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'],
                [b'application/octet-stream']
            )

    def test_post_upload_ok_11(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Transfer-Encoding: chunked'
            )

            self.client2.sendall(create_dummy_body(8192, chunk_size=4096))
            self.client2.sendall(b'X')

            self.assertEqual(response.body(), create_dummy_body(8192))
            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'],
                [b'application/octet-stream']
            )

    def test_post_upload2_ok_11(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Transfer-Encoding: chunked'
            )

            self.client2.sendall(create_dummy_body(65536, chunk_size=4096))

            self.assertEqual(response.body(), create_dummy_body(65536))
            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'],
                [b'application/octet-stream']
            )

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

    def test_post_upload_maxqueue(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload?maxqueue HTTP/1.0',
                body=create_dummy_body(8192)
            )

            self.assertEqual(response.body(), b'')

    def test_post_upload_multipart_11(self):
        with self.client2:
            boundary = b'----MultipartBoundary'
            response = self.client2.send(
                b'POST /upload/multipart HTTP/1.1',
                b'Transfer-Encoding: chunked',
                b'Content-Type: multipart/form-data; boundary=%s' % boundary
            )

            self.client2.sendall(
                create_chunked_body(create_multipart_body(
                                    boundary,
                                    file1=create_dummy_data(4096),
                                    file2=create_dummy_data(524288)))
            )

            self.assertEqual(
                response.body(),
                b'name,type,data\r\n'
                b'file1,application/octet-stream,BEGINEND\r\n'
                b'file2,application/octet-stream,BEGIN---\r\n'
                b'file2,application/octet-stream,-----END\r\n'
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.headers[b'content-type'], [b'text/csv'])

    def test_post_upload_multipart_form(self):
        with self.client2:
            boundary = b'----MultipartBoundary'
            response = self.client2.send(
                b'POST /upload/multipart/form HTTP/1.1',
                b'Transfer-Encoding: chunked',
                b'Content-Type: multipart/form-data; boundary=%s' % boundary
            )

            self.client2.sendall(
                create_chunked_body(create_multipart_body(
                                    boundary,
                                    text=b'Hello, World!',
                                    file=create_dummy_data(262144)))
            )

            self.assertEqual(response.body(), b'BEGINHello, World!END')
            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')

    def test_post_upload_multipart_form_fragmented(self):
        with self.client2:
            boundary = b'----MultipartBoundary'
            self.client2.send(
                b'POST /upload/multipart/form HTTP/1.1',
                b'Transfer-Encoding: chunked',
                b'Content-Type: multipart/form-data; boundary=%s' % boundary
            )
            self.client2.sendall(
                create_chunked_body(create_multipart_body(
                                    boundary,
                                    text=b'Hello, World!',
                                    file=create_dummy_data(524288)))
            )

            response = self.client2.end()

            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')

    def test_post_chunked_payloadtoolarge(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Transfer-Encoding: chunked'
            )

            self.client2.sendall(
                create_dummy_body(1048576 + 8192, chunk_size=16384)
            )

            self.assertEqual(response.body(), b'payload too large')
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_payloadtoolarge(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Content-Length: %d' % (1048576 + 8192)
            )

            self.client2.sendall(b'\x00')

            self.assertEqual(response.body(), b'Payload Too Large')
            self.assertEqual(response.status, 413)
            self.assertEqual(response.message, b'Payload Too Large')
            self.assertFalse(
                b'application/octet-stream' in
                response.headers[b'content-type']
            )

    def test_continue(self):
        with self.client2:
            body = create_dummy_body(65536)
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Content-Length: %d' % len(body),
                b'Expect: 100-continue'
            )

            self.assertEqual(response.body(), b'')
            self.assertEqual(response.status, 100)
            self.assertEqual(response.message, b'Continue')

            self.client2.sendall(body)

            self.assertEqual(response.body(), body)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertTrue(
                b'application/octet-stream' in
                response.headers[b'content-type']
            )

    def test_expectationfailed(self):
        with self.client2:
            response = self.client2.send(
                b'POST /upload HTTP/1.1',
                b'Content-Length: %d' % (2 * 1048576 + 16384),
                b'Expect: 100-continue'
            )

            self.client2.sendall(b'\x00')

            self.assertEqual(response.body(), b'Expectation Failed')
            self.assertEqual(response.status, 417)
            self.assertEqual(response.message, b'Expectation Failed')
            self.assertFalse(
                b'application/octet-stream' in
                response.headers[b'content-type']
            )

    def test_get_notfound_10(self):
        with self.client:
            response = self.client.send(b'GET /invalid HTTP/1.0')

            self.assertEqual(response.header.version, b'HTTP/1.0')
            self.assertEqual(response.status, 404)
            self.assertEqual(response.message, b'Not Found')

    def test_get_notfound_11(self):
        with self.client:
            response = self.client.send(b'GET /invalid HTTP/1.1')

            self.assertEqual(response.header.version, b'HTTP/1.1')
            self.assertEqual(response.status, 404)
            self.assertEqual(response.message, b'Not Found')

    def test_get_notfound_close_10(self):
        with self.client:
            response = self.client.send(
                b'GET /invalid HTTP/1.0',
                b'Connection: close'
            )

            self.assertEqual(response.header.version, b'HTTP/1.0')
            self.assertEqual(response.status, 404)
            self.assertEqual(response.message, b'Not Found')

    def test_get_notfound_keepalive_10(self):
        with self.client:
            response = self.client.send(
                b'GET /invalid HTTP/1.0',
                b'Connection: keep-alive'
            )

            self.assertEqual(response.header.version, b'HTTP/1.0')
            self.assertEqual(response.status, 404)
            self.assertEqual(response.message, b'Not Found')

    def test_get_notfound_close_11(self):
        with self.client:
            response = self.client.send(
                b'GET /invalid HTTP/1.1',
                b'Connection: close'
            )

            self.assertEqual(response.header.version, b'HTTP/1.1')
            self.assertEqual(response.status, 404)
            self.assertEqual(response.message, b'Not Found')

    def test_get_notfound_keepalive_11(self):
        with self.client:
            response = self.client.send(
                b'GET /invalid HTTP/1.1',
                b'Connection: keep-alive'
            )

            self.assertEqual(response.header.version, b'HTTP/1.1')
            self.assertEqual(response.status, 404)
            self.assertEqual(response.message, b'Not Found')

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

    def test_sec_content_length_and_transfer_encoding(self):
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

    def test_sec_double_content_length(self):
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

    def test_sec_empty_content_length(self):
        with self.client:
            response = self.client.send(
                b'GET /upload HTTP/1.1',
                b'Content-Length: '
            )

            self.assertEqual(response.body(), b'bad Content-Length')
            self.assertEqual(response.status, 400)
            self.assertEqual(response.message, b'Bad Request')

    def test_requesttimeout(self):
        with self.client1:
            self.client1.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\n')

            response = self.client1.end()

            self.assertEqual(response.body(), b'request timeout after 1s')
            self.assertEqual(response.status, 408)
            self.assertEqual(response.message, b'Request Timeout')

    def test_recv_timeout(self):
        with self.client1:
            response = self.client1.send(b'GET /timeouts?recv HTTP/1.1')

            self.assertEqual(response.body(), b'recv timeout')
            self.assertEqual(response.status, 408)
            self.assertEqual(response.message, b'Request Timeout')

    def test_handler_timeout(self):
        with self.client1:
            response = self.client1.send(b'GET /timeouts?handler HTTP/1.1')

            self.assertEqual(response.body(), b'Internal Server Error')
            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')

    def test_close_timeout(self):
        with self.client1:
            response = self.client1.send(b'GET /timeouts?close HTTP/1.1')

            self.assertEqual(response.body(), b'')

    def test_sse(self):
        with self.client:
            response = self.client.send(b'GET /sse HTTP/1.1')
            body = response.body()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(
                response.headers[b'content-type'], [b'text/event-stream']
            )
            self.assertEqual(
                response.headers[b'cache-control'],
                [b'no-cache, must-revalidate']
            )
            self.assertTrue(b'data: Hel\ndata: lo\nevent: hello\n\n' in body)
            self.assertTrue(b'data: Wor\nid: foo\n\n' in body)
            self.assertTrue(b'data: ld!\nretry: 10000\n\n' in body)

    def test_sse_error(self):
        with self.client:
            response = self.client.send(b'GET /sse?error HTTP/1.1')

            self.assertEqual(response.status, 500)
            self.assertEqual(response.message, b'Internal Server Error')

    def test_reload(self):
        if sys.platform != 'linux':
            return

        with self.client:
            response = self.client.send(
                b'GET /reload?%f HTTP/1.0' % time.time()
            )
            body1 = response.body()

            self.assertFalse(body1 == b'')
            body2 = body1

            for _ in range(10):
                time.sleep(1)

                with self.client:
                    response = self.client.send(b'GET /reload HTTP/1.1')
                    body2 = response.body()

                    self.assertFalse(body2 == b'')

                    if body2 != body1:
                        break

            self.assertFalse(body2 == body1)

    def test_mount_subsub_with_middleware(self):
        with self.client:
            response = self.client.send(b'GET /sub/subsub/mount/ HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'/sub/subsub')

    def test_mount_sub_no_middleware(self):
        with self.client:
            response = self.client.send(b'GET /sub/whatevermount HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'/')

    def test_class_get(self):
        with self.client:
            response = self.client.send(b'GET /resource HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.message, b'OK')
            self.assertEqual(response.body(), b'Hello, World!')

    def test_class_post_methodnotallowed(self):
        with self.client:
            response = self.client.send(b'PUT /resource HTTP/1.1')

            self.assertEqual(response.status, 405)
            self.assertEqual(response.message, b'Method Not Allowed')
            self.assertEqual(response.body(), b'Method Not Allowed')
            self.assertEqual(response.headers[b'allow'], [b'GET'])

    def test_redirect(self):
        with self.client:
            response = self.client.send(b'PUT /redirect?303 HTTP/1.0')

            self.assertEqual(response.status, 302)
            self.assertEqual(response.message, b'Found')
            self.assertEqual(response.url, b'/new')

    def test_redirect_301(self):
        with self.client:
            response = self.client.send(b'PUT /redirect?301 HTTP/1.0')

            self.assertEqual(response.status, 301)
            self.assertEqual(response.message, b'Moved Permanently')
            self.assertEqual(response.url, b'/new')

    def test_redirect_303(self):
        with self.client:
            response = self.client.send(b'PUT /redirect?303 HTTP/1.1')

            self.assertEqual(response.status, 303)
            self.assertEqual(response.message, b'See Other')
            self.assertEqual(response.url, b'/new')


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
            'tests', pattern='test_http*.py'
        )
        unittest.TextTestRunner().run(suite)
    finally:
        if p.is_alive():
            os.kill(p.pid, signal.SIGINT)
            p.join()
