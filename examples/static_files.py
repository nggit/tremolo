#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: nggit
# Description: Serving static files with StaticMiddleware

from tremolo import Application
from middlewares import StaticMiddleware


app = Application()

# apply middleware
# `document_root` is local folder in your computer
StaticMiddleware(app, document_root='public')


if __name__ == '__main__':
    app.run('0.0.0.0', 8004)
