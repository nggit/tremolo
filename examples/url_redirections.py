#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: Anggit Arfanto
# Description: URL Redirections

from tremolo import Application

app = Application()


@app.route('/example')
async def redirect_handler(response, **server):
    # redirection is basically just to set the header and return an empty body
    response.set_status(301, 'Moved Permanently')
    response.set_header('Location', 'http://example.com/')
    return ''


if __name__ == '__main__':
    app.run('0.0.0.0', 8000)
