#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: Anggit Arfanto
# Description: Module-based Views. Maps URLs to module names and methods.

from tremolo import Application
from utils import add_package

app = Application()

# http://localhost:8000/fruits       -> fruits.get()
# http://localhost:8000/fruits/apple -> fruits.apple.get()
add_package('fruits', app)

if __name__ == '__main__':
    app.run('0.0.0.0', 8000)
