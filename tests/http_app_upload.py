#!/usr/bin/env python3

import os
import sys

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo import Application  # noqa: E402

app = Application()


@app.route('/submitform')
def post_form(**server):
    request = server['request']

    request.form(max_size=8192)

    data = []

    for name, value in request.params['post'].items():
        data.append('%s=%s' % (name, value[0]))

    # b'user=myuser&pass=mypass'
    return '&'.join(data)


@app.route('/upload')
def upload(request, content_type=b'application/octet-stream', **server):
    if request.query_string == b'maxqueue':
        request.protocol.options['max_queue_size'] = 0

    try:
        size = int(request.query['size'][0])
        yield request.read(0) + request.read(size)
    except KeyError:
        body = bytearray()

        for data in request.stream():
            body.extend(data)

        yield body

        for data in request.stream():
            # should not raised
            raise Exception('EOF!!!')


@app.route('/upload/multipart')
async def upload_multipart(request, response, stream=False, **server):
    assert server != {}
    assert 'request' not in server
    assert 'response' not in server

    response.set_content_type(b'text/csv')

    # should be ignored
    yield b''

    yield b'name,type,data\r\n'

    # should be ignored
    yield b''

    # stream multipart file upload then send it back as csv
    async for part in request.files(max_files=1):
        yield b'%s,%s,%s\r\n' % (part['name'].encode(),
                                 part['type'].encode(),
                                 (part['data'][:5] + part['data'][-3:]))

    async for part in request.files(max_file_size=262144):
        if part['eof']:
            part['data'] = b'-----' + part['data'][-3:]
        else:
            part['data'] = part['data'][:5] + b'---'

        yield b'%s,%s,%s\r\n' % (part['name'].encode(),
                                 part['type'].encode(),
                                 (part['data'][:5] + part['data'][-3:]))

    async for part in request.files():
        # should not raised
        raise Exception('EOF!!!')


@app.route('/upload/multipart/form')
async def upload_multipart_form(request):
    form_data = await request.form(max_size=262144)
    files = request.params.files

    yield files['file'][0]['data'][:5]  # b'BEGIN'
    yield form_data['text'][0].encode()  # b'Hello, World!'
    yield files['file'][0]['data'][-3:]  # b'END'


if __name__ == '__main__':
    app.run('127.0.0.1', port=28000, debug=True, reload=True,
            client_max_body_size=1048576, ws_max_payload_size=73728)

# don't remove this; needed by test_http_range.py
# END
