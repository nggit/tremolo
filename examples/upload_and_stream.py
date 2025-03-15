#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: nggit
# Description: Upload and stream multipart/form-data.

from tremolo import Application

app = Application()


@app.route('/')
async def index():
    return (
        '<form action="/upload" method="post" enctype="multipart/form-data">'
        '<input type="file" name="file" />'
        '<input type="submit" value="Upload (Max. 16MiB)" />'
        '</form>'
    )


@app.route('/upload')
async def upload(request, response):
    # no worries, if the file is larger than `max_file_size`
    # it can still be read continuously bit by bit according to this size
    files = request.files(max_file_size=16384)  # 16KiB

    # read the initial part to get `Content-Type` information
    part = await anext(files)

    # send it back to the client
    response.set_content_type(part['type'])
    yield part['data']

    # read while sending the rest.
    # NOTE: most clients do not support it. hence our output queue can be full
    async for part in files:
        print(
            'Sending %s (len=%d, eof=%s)' % (part['filename'],
                                             len(part['data']),
                                             part['eof'])
        )
        yield part['data']


if __name__ == '__main__':
    app.run(
        '0.0.0.0', 8000, client_max_body_size=16 * 1048576, max_queue_size=1024
    )
