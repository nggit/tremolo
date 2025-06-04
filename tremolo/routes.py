# Copyright (c) 2023 nggit

import re

from functools import wraps

from . import handlers
from .utils import getoptions, is_async, to_sync


class Routes(dict):
    def __init__(self):
        self[0] = [
            (400, handlers.error_400, {}),
            (404, handlers.error_404, dict(request=None,
                                           globals=None,
                                           status=(404, b'Not Found'),
                                           stream=False)),
            # must be at the very end
            (500, handlers.error_500, {})
        ]
        self[1] = [
            (
                b'^/+(?:\\?.*)?$',
                handlers.index, dict(status=(503, b'Service Unavailable'))
            )
        ]
        self[-1] = []

    def add(self, func, path='/', kwargs=None):
        if not kwargs:
            kwargs = getoptions(func)

        if path.startswith('^') or path.endswith('$'):
            pattern = path.encode('latin-1')
            self[-1].append((pattern, func, kwargs))
        else:
            path = path.split('?', 1)[0].strip('/').encode('latin-1')

            if path == b'':
                key = 1
                pattern = self[1][0][0]
                self[key] = [(pattern, func, kwargs)]
            else:
                parts = path.split(b'/', 254)
                key = bytes([len(parts)]) + parts[0]
                pattern = b'^/+%s(?:/+)?(?:\\?.*)?$' % path

                if key in self:
                    self[key].append((pattern, func, kwargs))
                else:
                    self[key] = [(pattern, func, kwargs)]

    def compile(self, executor=None):
        for key in self:
            for i, (pattern, func, kwargs) in enumerate(self[key]):
                if isinstance(pattern, bytes):
                    pattern = re.compile(pattern)

                if executor is None or is_async(func):
                    wrapper = func
                else:
                    @wraps(func)
                    def wrapper(func, kwargs, request, response, **server):
                        server['request'] = to_sync(request, server['loop'])
                        server['response'] = to_sync(response, server['loop'])

                        return executor.submit(func.__wrapped__, kwargs=server)

                self[key][i] = (pattern, wrapper, kwargs)
