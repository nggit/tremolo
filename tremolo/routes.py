# Copyright (c) 2023 nggit

import re

from . import handlers
from .utils import getoptions


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

    def compile(self):
        for key in self:
            for i, h in enumerate(self[key]):
                pattern, *handler = h

                if isinstance(pattern, bytes):
                    self[key][i] = (re.compile(pattern), *handler)
