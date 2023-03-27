#!/usr/bin/env python3

import multiprocessing as mp
import unittest

HOST = 'localhost'
PORT = 28000

# a simple HTTP client for tests
def getcontents(host='localhost',
                port=80,
                method='GET',
                path='/',
                version='1.1',
                headers=[],
                data='',
                raw=b''):
    import socket
    import time

    if raw == b'':
        content_length = len(data)

        if content_length > 0:
            if headers == []:
                headers.append('Content-Type: application/x-www-form-urlencoded')

            headers.append('Content-Length: {:d}'.format(content_length))

        raw = '{:s} {:s} HTTP/{:s}\r\nHost: {:s}:{:d}\r\n{:s}\r\n\r\n{:s}'.format(
            method, path, version, host, port, '\r\n'.join(headers), data).encode(encoding='latin-1')

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(5)

        while sock.connect_ex((host, port)) != 0:
            time.sleep(1)

        sock.sendall(raw)

        response_data = bytearray()
        buf = True

        while buf:
            buf = sock.recv(4096)
            response_data.extend(buf)

            header_end = response_data.find(b'\r\n\r\n')
            response_header = response_data[:header_end]

            if header_end > -1:
                if response_header.lower().startswith('http/{:s} 100 continue'.format(version).encode(encoding='latin-1')):
                    del response_data[:]
                    continue

                if method.upper() == 'HEAD':
                    break
                elif (response_header.lower().find(b'\r\ntransfer-encoding: chunked') == -1
                            and response_data[header_end + 4:] != b''
                       ):
                    break
                elif response_data.endswith(b'\r\n0\r\n\r\n'):
                    break

        return response_header, response_data[header_end + 4:]

def chunked_detected(header):
    return header.lower().find(b'\r\ntransfer-encoding: chunked') > -1

def valid_chunked(body):
    if not body.endswith(b'\r\n0\r\n\r\n'):
        return False

    while body != b'0\r\n\r\n':
        i = body.find(b'\r\n')

        if i == -1:
            return False

        try:
            chunk_size = int(body[:i].split(b';')[0], 16)
        except ValueError:
            return False

        del body[:i + 2]

        if body[chunk_size:chunk_size + 2] != b'\r\n':
            return False

        del body[:chunk_size + 2]

    return True

def create_dummy_body(size, chunk_size=0):
    data = bytearray(size)

    if chunk_size <= 1:
        return data

    result = bytearray()

    for _ in range(len(data) // chunk_size):
        chunk = data[:chunk_size]
        result.extend(b'%X\r\n%s\r\n' % (len(chunk), chunk))

    return result + b'0\r\n\r\n'

#### TESTS ####

class TestQuick(unittest.TestCase):
    tests_run = 0

    def setUp(self):
        self.__class__.tests_run += 1
        print('\r\033[2K{0:d}. {1:s}'.format(self.__class__.tests_run, self.id().split('.')[-1]))

    def test_get_middleware_11(self):
        header, body = getcontents(host=HOST, port=PORT, method='FOO', path='/', version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 405 Method Not Allowed')

    def test_get_ok_10(self):
        header, body = getcontents(host=HOST, port=PORT, method='GET', path='/', version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 503 Service Unavailable')
        self.assertFalse(chunked_detected(header))
        self.assertTrue(header.find(b'\r\nX-Foo: bar') > -1 and header.find(b'Set-Cookie: sess=www') > -1)

    def test_get_ok_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='GET',
                                   path='/page/101?a=111&a=xyz&b=222',
                                   version='1.1',
                                   headers=['Cookie: a=123', 'Cookie: a=xxx, yyy'])

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_form_ok_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   method='POST',
                                   path='/page/102?a=111&a=xyz&b=222',
                                   version='1.1',
                                   data='username=myuser&password=mypass')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload_ok_10(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload HTTP/1.0\r\nHost: localhost:28000\r\n' +
                                       b'Content-Length: 8192\r\n\r\n' +
                                       create_dummy_body(8192))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload2_ok_10(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload2 HTTP/1.0\r\nHost: localhost:28000\r\n' +
                                       b'Content-Length: 65536\r\n\r\n' +
                                       create_dummy_body(65536))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 200 OK')
        self.assertFalse(chunked_detected(header))

    def test_post_upload_ok_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload HTTP/1.1\r\nHost: localhost:28000\r\n' +
                                       b'Transfer-Encoding: chunked\r\n\r\n' +
                                       create_dummy_body(8192, chunk_size=4096))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload2_ok_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload2 HTTP/1.1\r\nHost: localhost:28000\r\n' +
                                       b'Transfer-Encoding: chunked\r\n\r\n' +
                                       create_dummy_body(64 * 1024, chunk_size=4096))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_post_upload3_payloadtoolarge_11(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload3 HTTP/1.1\r\nHost: localhost:28000\r\n' +
                                       b'Transfer-Encoding: chunked\r\n\r\n' +
                                       create_dummy_body(2 * 1048576 + 16 * 1024, chunk_size=16 * 1024))

    def test_payloadtoolarge(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload3 HTTP/1.1\r\nHost: localhost:28000\r\n' +
                                       (b'Content-Length: %d\r\n\r\n\x00' %  (2 * 1048576 + 16 * 1024)))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 413 Payload Too Large')
        self.assertEqual(body, b'Payload Too Large')

    def test_continue(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload2 HTTP/1.1\r\nHost: localhost:28000\r\nExpect: 100-continue\r\n' +
                                       (b'Content-Length: %d\r\n\r\n' %  (64 * 1024)) +
                                       create_dummy_body(64 * 1024))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 200 OK')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_expectationfailed(self):
        header, body = getcontents(host=HOST,
                                   port=PORT,
                                   raw=b'POST /upload3 HTTP/1.1\r\nHost: localhost:28000\r\nExpect: 100-continue\r\n' +
                                       (b'Content-Length: %d\r\n\r\n\x00' %  (2 * 1048576 + 16 * 1024)))

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 417 Expectation Failed')
        self.assertEqual(body, b'Expectation Failed')

    def test_get_notfound_10(self):
        header, body = getcontents(host=HOST, port=PORT, method='GET', path='/invalid', version='1.0')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_11(self):
        header, body = getcontents(host=HOST, port=PORT, method='GET', path='/invalid', version='1.1')

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_notfound_close_10(self):
        header, body = getcontents(
            host=HOST, port=PORT, method='GET', path='/invalid', version='1.0', headers=['Connection: close']
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_keepalive_10(self):
        header, body = getcontents(
            host=HOST, port=PORT, method='GET', path='/invalid', version='1.0', headers=['Connection: keep-alive']
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.0 404 Not Found')
        self.assertFalse(chunked_detected(header))

    def test_get_notfound_close_11(self):
        header, body = getcontents(
            host=HOST, port=PORT, method='GET', path='/invalid', version='1.1', headers=['Connection: close']
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_notfound_keepalive_11(self):
        header, body = getcontents(
            host=HOST, port=PORT, method='GET', path='/invalid', version='1.1', headers=['Connection: keep-alive']
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 404 Not Found')

        if chunked_detected(header):
            self.assertTrue(valid_chunked(body))

    def test_get_badrequest(self):
        header, body = getcontents(
            host=HOST, port=PORT, raw=b'GET HTTP/\r\nHost: localhost:28000\r\n\r\n'
        )

        self.assertEqual(header[:header.find(b'\r\n')], b'HTTP/1.1 400 Bad Request')

    def test_badrequest_notarequest(self):
        data = getcontents(
            host=HOST, port=PORT, raw=b' HTTP/\r\nHost: localhost:28000\r\n\r\n'
        )

        self.assertEqual(data, (b'', b''))

    def test_badrequest(self):
        data = getcontents(
            host=HOST, port=PORT, raw=b'GET / HTTP/1.1\r\nHost: localhost:28000\r\n' + b'\x00' * 8192
        )

        self.assertEqual(data, (b'', b''))

    def test_headertoolarge(self):
        data = getcontents(
            host=HOST, port=PORT, raw=b'GET / HTTP/1.1\r\nHost: localhost:28000\r\n' + b'\x00' * 8192 + b'\r\n\r\n'
        )

        self.assertEqual(data, (b'', b''))

#### SERVER ####

from tremolo import Tremolo

app = Tremolo()

@app.on_request
async def my_request_middleware(**server):
    request = server['request']
    response = server['response']

    if request.is_valid and request.method not in (b'GET', b'POST'):
        response.set_status(405, 'Method Not Allowed')
        response.set_content_type('text/plain')

        return b'Request method %s is not supported!' % request.method

    # test response object
    response.set_header('X-Foo', 'bar')
    response.set_cookie('sess', 'www')

@app.route(r'^/page/(?P<page_id>\d+)')
async def my_page(**server):
    request = server['request']
    page_id = request.params['url'].get('page_id')

    assert page_id is not None, 'empty page_id'

    if page_id == b'101':
        assert request.headers.get(b'cookie') == [b'a=123', b'a=xxx, yyy']
        assert request.headers.getlist(b'cookie') == [b'a=123', b'a=xxx', b'yyy']
        assert request.cookies['a'] == ['123', 'xxx, yyy']

    elif page_id == b'102':
        assert request.headers.get(b'cookie') == None
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
    print('  PATH:',           request.path)
    print('  PARAMS:',         request.params)
    print('  QUERY_STRING:',   request.query)
    print('  COOKIES:',        request.cookies)
    print('  VERSION:',        request.version)

    # test logger
    server['logger'].info(b'You are on page %s' % page_id)
    yield b'You are on page ' + page_id

@app.route('/upload')
async def upload_ok(**server):
    assert await server['request'].body() == create_dummy_body(8192), 'integrity error'

    return 'OK'

@app.route('/upload2')
async def upload2_ok(**server):
    assert await server['request'].body() == create_dummy_body(64 * 1024), 'integrity error'

    return 'OK'

@app.route('/upload3')
async def upload3_payloadtoolarge(**server):
    await server['request'].body()

    return 'OK'

# test multiple ports
app.listen(28001)
app.listen(28002)

if __name__ == '__main__':
    mp.set_start_method('spawn')
    p = mp.Process(target=app.run, kwargs=dict(host='', port=PORT, debug=False))
    p.start()

    try:
        unittest.main()
    finally:
        p.terminate()
