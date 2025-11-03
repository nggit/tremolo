# SPDX-License-Identifier: MIT
# Copyright (c) 2023 Anggit Arfanto

from .tremolo import __version__, Tremolo, Tremolo as Application  # noqa: F401
from . import exceptions  # noqa: F401


def run(app, **options):
    if 'host' not in options:
        options['host'] = '127.0.0.1'

    if 'port' not in options:
        options['port'] = 8000

    Tremolo().run(app=app, **options)
