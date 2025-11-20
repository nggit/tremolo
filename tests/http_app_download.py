#!/usr/bin/env python3

import concurrent.futures
import os
import sys

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo import Application  # noqa: E402

TEST_FILE = __file__

app = Application()


@app.route('/download')
async def download(request, response):
    if request.query_string == b'executor':
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            await response.sendfile(
                TEST_FILE, content_type='text/plain', executor=executor
            )
    else:
        await response.sendfile(
            TEST_FILE,
            count=os.stat(TEST_FILE).st_size + 10, content_type=b'text/plain'
        )


if __name__ == '__main__':
    app.run('127.0.0.1', port=28000, debug=True, reload=True,
            client_max_body_size=1048576, ws_max_payload_size=73728)

# don't remove this; needed by test_http_range.py
# END
