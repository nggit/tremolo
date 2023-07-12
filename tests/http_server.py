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

    # these should appear in the next middlewares or handlers
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

        # sys.stdout.buffer.write(b''.join(response.header))
        # print()


@app.route('/getheaderline')
async def get_headerline(**server):
    request = server['request']

    assert (b'%s?%s' % (request.path, request.query_string)) == request.url

    # b'GET /getheaderline HTTP/1.1'
    return b'%s %s HTTP/%s' % (
        request.method,
        request.url,
        request.version
    )


@app.route('/gethost')
async def get_host(**server):
    # b'localhost:28000'
    return server['request'].host


@app.route('/getquery')
async def get_query(**server):
    request = server['request']

    assert request.query['a'] == ['111', 'xyz']
    assert request.query['b'] == ['222']

    data = []

    for name, value in request.query.items():
        data.append('{:s}={:s}'.format(name, value[0]))

    # b'a=111&b=222'
    return '&'.join(data)


@app.route(r'^/page/(?P<page_id>\d+)')
async def get_page(**server):
    # b'101'
    return server['request'].params['path'].get('page_id')


@app.route('/getcookies')
async def get_cookies(**server):
    request = server['request']

    assert request.headers.get(b'cookie') == [b'a=123', b'a=xxx, yyy']
    assert request.cookies['a'] == ['123', 'xxx, yyy']

    # b'a=123, a=xxx, yyy'
    return b', '.join(request.headers.getlist(b'cookie'))


@app.route('/submitform')
async def post_form(**server):
    request = server['request']

    await request.form()

    data = []

    for name, value in request.params['post'].items():
        data.append('{:s}={:s}'.format(name, value[0]))

    # b'user=myuser&pass=mypass'
    return '&'.join(data)


@app.route('/upload')
async def upload(content_type=b'application/octet-stream', **server):
    return await server['request'].body()


@app.route('/upload/multipart')
async def upload_multipart(**server):
    server['response'].set_content_type(b'text/csv')
    yield b'name,length,type,data\r\n'

    # stream multipart file upload then send it back as csv
    async for info, data in server['request'].files():
        yield b'%s,%d,%s,%s\r\n' % (info['name'].encode(),
                                    info['length'],
                                    info['type'].encode(),
                                    (data[:5] + data[-3:]))


@app.route('/download')
async def download(**server):
    await server['response'].sendfile(TEST_FILE, content_type=b'text/plain')

# test multiple ports
app.listen(HTTP_PORT + 1, request_timeout=2)
app.listen(HTTP_PORT + 2)

if __name__ == '__main__':
    app.run(HTTP_HOST, port=HTTP_PORT, debug=True)

# END