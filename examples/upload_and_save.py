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

    # keep track of incomplete writings
    incomplete = set()

    try:
        # read while writing the file(s).
        # `part` represents a field/file received in a multipart request
        async for part in files:
            filename = quote(part.get('filename', ''))

            if not filename:
                continue

            with open('Uploaded_' + filename, 'wb') as fp:
                incomplete.add(fp)

                # stream a (possibly) large part in chunks
                async for data in part.stream():
                    print('Writing %s (len=%d, eof=%s)' % (filename,
                                                           len(data),
                                                           part['eof']))
                    fp.write(data)

                incomplete.discard(fp)  # completed :)

            filename = filename.encode()
            content_type = quote(part['type']).encode()

            yield (
                b'File <a href="/download?type=%s&filename=%s">%s</a> '
                b'was uploaded.<br />' % (content_type, filename, filename)
            )
    finally:
        while incomplete:
            path = incomplete.pop().name
            print('Upload canceled, removing incomplete file: %s' % path)
            os.unlink(path)

    yield b''


@app.route('/download')
async def download(request, response):
    # prepend / append a hardcoded string.
    # do not let the user freely determine the path
    path = 'Uploaded_' + quote(request.query['filename'][0])
    content_type = request.query['type'][0]

    await response.sendfile(path, content_type=content_type)


if __name__ == '__main__':
    # 100MiB is a nice limit due to the default `app_handler_timeout=120`
    # (120 seconds). however, it's perfectly fine to increase those limits
    app.run('0.0.0.0', 8000, client_max_body_size=100 * 1048576)
