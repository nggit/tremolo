# Copyright (c) 2023 nggit

import re

from functools import wraps

from . import handlers
from .utils import getoptions, is_async, to_sync


class Routes(dict):
    def __init__(self):
        self[0] = [
            (400, handlers.error_400, {}, {}),
            (401, None, {}, {}),
            (402, None, {}, {}),
            (403, None, {}, {}),
            (404, handlers.error_404, {}, {}),
            (405, handlers.error_405, {}, {})] + [
            (code, handlers.error_500 if code == 500 else None, {}, {})
            for code in range(406, 512)
        ]
        self[1] = [
            (b'^/+(?:\\?.*)?$', handlers.index, getoptions(handlers.index), {})
        ]
        self[-1] = []

    def add(self, func, path='/', kwargs=None, **options):
        if not kwargs:
            kwargs = getoptions(func)

        key = -1

        if path.endswith('$'):
            pattern = path.rstrip('$').encode('latin-1') + b'(?:\\?.*)?$'
        elif path.startswith('^'):
            pattern = path.encode('latin-1')
        else:
            path = path.split('?', 1)[0].strip('/').encode('latin-1')

            if path == b'':
                key = 1
                pattern = self[1][0][0]
            else:
                parts = path.split(b'/', 254)
                key = bytes([len(parts)]) + parts[0]
                pattern = b'^/+%s(?:/+)?(?:\\?.*)?$' % path

        if key != 1 and key in self:
            self[key].append((pattern, func, kwargs, options))
        else:
            self[key] = [(pattern, func, kwargs, options)]

    def compile(self, executor=None):
        for key in self:
            for i, (pattern, func, kwargs, options) in enumerate(self[key]):
                if func is None:
                    continue

                if isinstance(pattern, bytes):
                    pattern = re.compile(pattern)

                if executor is None or is_async(func):
                    wrapper = func
                else:
                    @wraps(func)
                    def wrapper(func, kwargs, request, response,
                                self=None, **server):
                        server['request'] = to_sync(request, server['loop'])
                        server['response'] = to_sync(response, server['loop'])

                        if self is None:
                            func = func.__wrapped__
                        else:  # use bound method
                            func = getattr(self, func.__name__)

                        return executor.submit(func, kwargs=server)

                self[key][i] = (pattern, wrapper, kwargs, options)
