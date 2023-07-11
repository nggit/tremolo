#!/usr/bin/env python3

__all__ = ('app', 'HTTP_PORT', 'HTTP_HOST', 'TEST_FILE')

import os  # noqa: E402
import sys  # noqa: E402

# makes imports relative from the repo directory
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from tremolo import Tremolo  # noqa: E402
from tremolo.exceptions import BadRequest  # noqa: E402
from tests.utils import create_dummy_body  # noqa: E402

HTTP_HOST = 'localhost'
HTTP_PORT = 28000
TEST_FILE = __file__

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
    print('  HTTP_HTTP_HOST:',      request.host)
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


@app.route('/upload4')
async def upload4_ok(**server):
    async for info, data in server['request'].files():
        assert 'name' in info
        assert 'length' in info
        assert 'type' in info
        assert data[:5] == b'BEGIN'
        assert data[-3:] == b'END'

        print(info, data[-12:])

    return 'OK'


@app.route('/download')
async def download(**server):
    await server['response'].sendfile(TEST_FILE, content_type=b'text/plain')

# test multiple ports
app.listen(HTTP_PORT + 1, request_timeout=2)
app.listen(HTTP_PORT + 2)

if __name__ == '__main__':
    app.run(HTTP_HOST, port=HTTP_PORT, debug=True)

# END
