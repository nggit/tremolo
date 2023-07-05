#!/usr/bin/env python3

__all__ = ('run',)

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

from tremolo import Tremolo  # noqa: E402
from tremolo.exceptions import BadRequest  # noqa: E402
from tests.utils import (  # noqa: E402
    getcontents,
    chunked_detected,
    valid_chunked,
    create_dummy_body
)

HOST = 'localhost'
PORT = 28000


class QuickTest(unittest.TestCase):
    tests_run = 0

    def setUp(self):
        self.__class__.tests_run += 1
        print('\r\033[2K{0:d}. {1:s}'.format(self.__class__.tests_run,
                                             self.id().split('.')[-1]))

    def test_get_middleware_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='FOO',
                                   url='/',
                                   version='1.1')

        self.assertEqual(
            header[:header.find(b'\r\n')],
            b'HTTP/1.1 405 Method Not Allowed'
        )

    def test_get_ok_10(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
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
        header, body = getcontents(host=HOST,
                                   port=PORT,
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
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='POST',
                                   url='/page/102?a=111&a=xyz&b=222',
                                   version='1.1',
                                   data='username=myuser&password=mypass')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload_ok_10(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload HTTP/1.0\r\n' +
                                       b'Host: localhost:28000\r\n' +
                                       b'Content-Length: 8192\r\n\r\n' +
                                       create_dummy_body(8192))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload2_ok_10(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload2 HTTP/1.0\r\n' +
                                       b'Host: localhost:28000\r\n' +
                                       b'Content-Length: 65536\r\n\r\n' +
                                       create_dummy_body(65536))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload_ok_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload HTTP/1.1\r\n' +
                                       b'Host: localhost:28000\r\n' +
                                       b'Transfer-Encoding: chunked\r\n\r\n' +
                                       create_dummy_body(
                                           8192, chunk_size=4096))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload2_ok_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload2 HTTP/1.1\r\n' +
                                       b'Host: localhost:28000\r\n' +
                                       b'Transfer-Encoding: chunked\r\n\r\n' +
                                       create_dummy_body(
                                           64 * 1024, chunk_size=4096))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload3_payloadtoolarge_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload3 HTTP/1.1\r\n' +
                                       b'Host: localhost:28000\r\n' +
                                       b'Transfer-Encoding: chunked\r\n\r\n' +
                                       create_dummy_body(
                                           2 * 1048576 + 16 * 1024,
                                           chunk_size=16 * 1024))

    def test_payloadtoolarge(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload3 HTTP/1.1\r\n' +
                                       b'Host: localhost:28000\r\n' +
                                       (b'Content-Length: %d\r\n\r\n\x00' % (
                                           2 * 1048576 + 16 * 1024)))

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 413 Payload Too Large')
        self.assertEqual(body, b'Payload Too Large')

    def test_continue(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload2 HTTP/1.1\r\n' +
                                       b'Host: localhost:28000\r\n' +
                                       b'Expect: 100-continue\r\n' +
                                       (b'Content-Length: %d\r\n\r\n' % (
                                           64 * 1024)) +
                                       create_dummy_body(64 * 1024))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_expectationfailed(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload3 HTTP/1.1\r\n' +
                                       b'Host: localhost:28000\r\n' +
                                       b'Expect: 100-continue\r\n' +
                                       (b'Content-Length: %d\r\n\r\n\x00' % (
                                           2 * 1048576 + 16 * 1024)))

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 417 Expectation Failed')
        self.assertEqual(body, b'Expectation Failed')

    def test_get_notfound_10(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_notfound_close_10(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.0',
                                   headers=['Connection: close'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_keepalive_10(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.0',
                                   headers=['Connection: keep-alive'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_close_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.1',
                                   headers=['Connection: close'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_notfound_keepalive_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='GET',
                                   url='/invalid',
                                   version='1.1',
                                   headers=['Connection: keep-alive'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_badrequest(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'GET HTTP/\r\n' +
                                       b'Host: localhost:28000\r\n\r\n')

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')

    def test_badrequest_notarequest(self):
        data = getcontents(host=HOST,
                           port=PORT,
                           raw=b' HTTP/\r\nHost: localhost:28000\r\n\r\n')

        self.assertEqual(data, (b'', b''))

    def test_badrequest(self):
        data = getcontents(host=HOST,
                           port=PORT,
                           raw=b'GET / HTTP/1.1\r\n' +
                               b'Host: localhost:28000\r\n' + b'\x00' * 8192)

        self.assertEqual(data, (b'', b''))

    def test_headertoolarge(self):
        data = getcontents(host=HOST,
                           port=PORT,
                           raw=b'GET / HTTP/1.1\r\nHost: localhost:28000\r\n' +
                               b'\x00' * 8192 + b'\r\n\r\n')

        self.assertEqual(data, (b'', b''))

    def test_requesttimeout(self):
        data = getcontents(host=HOST,
                           port=28001,
                           raw=b'GET / HTTP/1.1\r\nHost: localhost:28001\r\n')

        self.assertEqual(data, (b'', b''))

    def test_download_10(self):
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertEqual(header.find(b'\r\nAccept-Ranges:'), -1)
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(
            header.find(
                b'\r\nContent-Length: %d' % os.stat(__file__).st_size) > 0
        )

    def test_download_11(self):
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')
        self.assertTrue(header.find(b'\r\nAccept-Ranges: bytes') > 0)
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(
            header.find(
                b'\r\nContent-Length: %d' % os.stat(__file__).st_size) > 0
        )

    def test_notmodified(self):
        mtime = os.path.getmtime(__file__)
        mdate = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(mtime))
        header, body = getcontents(host=HOST,
                                   port=28002,
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
        header, body = getcontents(host=HOST,
                                   port=28002,
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
            header.find(
                b'\r\nContent-Length: %d' % os.stat(__file__).st_size) > 0
        )

    def test_download_range(self):
        mtime = os.path.getmtime(__file__)
        mdate = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(mtime))
        header, body = getcontents(host=HOST,
                                   port=28002,
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
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=[
                                       'Range: bytes=%d-' % (
                                           os.stat(__file__).st_size - 5)
                                   ])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 206 Partial Content')
        self.assertEqual(body.strip(b'# \r\n'), b'END')
        self.assertTrue(header.find(b'\r\nContent-Type: text/plain') > 0)
        self.assertTrue(header.find(b'\r\nContent-Length: 5') > 0)

    def test_download_range_end(self):
        header, body = getcontents(host=HOST,
                                   port=28002,
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
        header, body = getcontents(host=HOST,
                                   port=28002,
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
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-2, 3'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad range')

    def test_badrange1(self):
        header, body = getcontents(host=HOST,
                                   port=28002,
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
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bits=2-1'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 400 Bad Request')
        self.assertEqual(body, b'bad range')

    def test_rangenotsatisfiable(self):
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=-10000000'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertEqual(body, b'Range Not Satisfiable')

    def test_rangenotsatisfiable1(self):
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=10000000-'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertEqual(body, b'Range Not Satisfiable')

    def test_rangenotsatisfiable2(self):
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-1'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertEqual(body, b'Range Not Satisfiable')

    def test_rangenotsatisfiable3(self):
        header, body = getcontents(host=HOST,
                                   port=28002,
                                   method='GET',
                                   url='/download',
                                   version='1.1',
                                   headers=['Range: bytes=2-10000000'])

        self.assertEqual(header[:header.find(b'\r\n')],
                         b'HTTP/1.1 416 Range Not Satisfiable')
        self.assertEqual(body, b'Range Not Satisfiable')


# SERVER #

app = Tremolo()


@app.on_request
async def my_request_middleware(**server):
    request = server['request']
    response = server['response']

    if not request.is_valid:
        raise BadRequest

    if request.method not in (b'GET', b'POST'):
        response.set_status(405, 'Method Not Allowed')
        response.set_content_type('text/plain')

        return b'Request method %s is not supported!' % request.method

    # test response object
    response.set_header('X-Foo', 'bar')
    response.set_cookie('sess', 'www')


@app.on_send
async def my_send_middleware(**server):
    response = server['response']
    name, data = server['context'].data

    if name == 'header':
        # test append_header()
        response.append_header(b'------------------')

        assert data + b'------------------' == b''.join(response.header)

        sys.stdout.buffer.write(b''.join(response.header))
        print()


@app.route(r'^/page/(?P<page_id>\d+)')
async def my_page(**server):
    request = server['request']
    page_id = request.params['path'].get('page_id')

    assert page_id is not None, 'empty page_id'

    if page_id == b'101':
        assert request.headers.get(b'cookie') == [b'a=123', b'a=xxx, yyy']
        assert request.headers.getlist(b'cookie') == [b'a=123',
                                                      b'a=xxx',
                                                      b'yyy']
        assert request.cookies['a'] == ['123', 'xxx, yyy']

    elif page_id == b'102':
        assert request.headers.get(b'cookie') is None
        assert request.headers.getlist(b'cookie') == []
        await request.form()
        assert request.params['post']['username'] == ['myuser']
        assert request.params['post']['password'] == ['mypass']

    assert request.query['a'] == ['111', 'xyz']
    assert request.query['b'] == ['222']

    # test request object
    print('  ROUTE:',          r'^/page/(?P<page_id>\d+)')
    print('  HTTP_HOST:',      request.host)
    print('  REQUEST_METHOD:', request.method)
    print('  REQUEST_URI:',    request.url)
    print('  PARAMS:',         request.params)
    print('  PATH:',           request.path)
    print('  QUERY:',          request.query)
    print('  QUERY_STRING:',   request.query_string)
    print('  COOKIES:',        request.cookies)
    print('  VERSION:',        request.version)

    # test logger
    server['logger'].info(b'You are on page %s' % page_id)
    yield b'You are on page ' + page_id


@app.route('/upload')
async def upload_ok(**server):
    assert await server['request'].body() == create_dummy_body(8192)

    return 'OK'


@app.route('/upload2')
async def upload2_ok(**server):
    assert await server['request'].body() == create_dummy_body(64 * 1024)

    return 'OK'


@app.route('/upload3')
async def upload3_payloadtoolarge(**server):
    await server['request'].body()

    return 'OK'


@app.route('/download')
async def download(**server):
    await server['response'].sendfile(__file__, content_type=b'text/plain')

# test multiple ports
app.listen(28001, request_timeout=2)
app.listen(28002)


def run():
    mp.set_start_method('spawn')
    p = mp.Process(
        target=app.run,
        kwargs=dict(host='', port=PORT, debug=False)
    )
    p.start()

    try:
        sys.modules['__main__'].QuickTest = QuickTest
        unittest.main()
    finally:
        p.terminate()


if __name__ == '__main__':
    run()

# END
