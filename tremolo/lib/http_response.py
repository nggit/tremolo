# Copyright (c) 2023 nggit

from datetime import datetime, timedelta
from urllib.parse import quote

from .response import Response

class HTTPResponse(Response):
    def __init__(self, protocol, request):
        super().__init__(protocol)

    async def set_cookie(self, name, value='', expires=0, path='/', domain=None, secure=False, httponly=False, samesite=None):
        if isinstance(name, str):
            name = name.encode(encoding='latin-1')

        value = quote(value).encode(encoding='latin-1')
        date_expired = (datetime.utcnow() + timedelta(seconds=expires)).strftime('%a, %d %b %Y %H:%M:%S GMT').encode(encoding='latin-1')
        path = quote(path).encode(encoding='latin-1')

        cookie = bytearray(b'Set-Cookie: %s=%s; expires=%s; max-age=%d; path=%s' % (name, value, date_expired, expires, path))

        for k, v in ((b'domain', domain), (b'samesite', samesite)):
            if v:
                cookie.extend(b'; %s=%s' % (k, bytes(quote(v), encoding='latin-1')))

        for k, v in ((secure, b'; secure'), (httponly, b'; httponly')):
            if k:
                cookie.extend(v)

        await self.write(cookie + b'\r\n', throttle=False)
        del cookie[:]

    async def set_header(self, name, value=''):
        if isinstance(name, str):
            name = name.encode(encoding='latin-1')

        if isinstance(value, str):
            value = value.encode(encoding='latin-1')

        await self.write(b'%s: %s\r\n' % (name, value), throttle=False)
