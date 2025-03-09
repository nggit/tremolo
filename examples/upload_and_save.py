#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: nggit
# Description: Upload, stream multipart/form-data and save.

import os
from urllib.parse import quote

from tremolo import Application

app = Application()


@app.route('/')
async def index():
    return (
        '<form action="/upload" method="post" enctype="multipart/form-data">'
        '<p><input type="file" name="file1" /></p>'
        '<p><input type="file" name="file2" /></p>'
        '<p><input type="submit" value="Upload (Max. 100MiB)" /></p>'
        '</form>'
    )


@app.route('/upload')
async def upload(request, response):
    # no worries, if the file is larger than `max_file_size`
    # it can still be read continuously bit by bit according to this size
    files = request.files(max_file_size=16384)  # 16KiB

    fp = None
    filename = None

    try:
        # read while writing the file(s).
        async for part in files:
            filename = quote(part.get('filename', ''))

            if not filename:
                continue

            if fp is None:
                fp = open('Uploaded_' + filename, 'wb')

            print('Writing %s (len=%d, eof=%s)' % (filename,
                                                   len(part['data']),
                                                   part['eof']))
            fp.write(part['data'])

            if part['eof']:
                fp.close()
                fp = None  # the next iteration will be another file
                filename = filename.encode()
                content_type = quote(part['type']).encode()

                yield (
                    b'File <a href="/download?type=%s&filename=%s">%s</a> '
                    b'was uploaded.<br />' % (content_type, filename, filename)
                )
    finally:
        if fp is not None:
            fp.close()
            print('Upload canceled, removing incomplete file: %s' % filename)
            os.unlink('Uploaded_' + filename)

    yield b''


@app.route('/download')
async def download(request, response):
    path = 'Uploaded_' + quote(request.query['filename'][0])
    content_type = request.query['type'][0]

    await response.sendfile(path, content_type=content_type)


if __name__ == '__main__':
    # 100MiB is a nice limit due to the default `app_handler_timeout=120`
    # (120 seconds). however, it's perfectly fine to increase those limits
    app.run('0.0.0.0', 8000, client_max_body_size=100 * 1048576)
