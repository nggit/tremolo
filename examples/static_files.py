#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: Anggit Arfanto
# Description: Serving static files with StaticMiddleware

from tremolo import Application
from middlewares import StaticMiddleware


app = Application()

# apply middleware
# `document_root` is local folder in your computer
StaticMiddleware(app, document_root='public', follow_symlinks=False)


if __name__ == '__main__':
    app.run('0.0.0.0', 8004, log_level='ERROR')
