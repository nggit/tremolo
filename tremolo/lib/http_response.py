# Copyright (c) 2023 nggit

from datetime import datetime, timedelta
from urllib.parse import quote

from .response import Response

class HTTPResponse(Response):
    def __init__(self, protocol, request):
        super().__init__(protocol)

        self._header = bytearray()
        self._request = request
        self._status = []
        self._content_type = []
        self._write_cb = self._on_write

    @property
    def header(self):
        return self._header

    def append_header(self, value):
        self._header.extend(value)

    def set_cookie(self, name, value='', expires=0, path='/', domain=None, secure=False, httponly=False, samesite=None):
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

        self._header.extend(cookie + b'\r\n')

    def set_header(self, name, value=''):
        if isinstance(name, str):
            name = name.encode(encoding='latin-1')

        if isinstance(value, str):
            value = value.encode(encoding='latin-1')

        self._header.extend(b'%s: %s\r\n' % (name, value))

    def set_status(self, status=200, message=b'OK'):
        if isinstance(message, str):
            message = message.encode(encoding='latin-1')

        self._status.append((status, message))

    def get_status(self):
        try:
            return self._status.pop()
        except IndexError:
            return 200, b'OK'

    def set_content_type(self, content_type=b'text/html; charset=utf-8'):
        if isinstance(content_type, str):
            content_type = content_type.encode(encoding='latin-1')

        self._content_type.append(content_type)

    def get_content_type(self):
        try:
            return self._content_type.pop()
        except IndexError:
            return b'text/html; charset=utf-8'

    def set_write_callback(self, write_cb):
        self._write_cb = write_cb

    async def end(self, data=None):
        if isinstance(data, (bytes, bytearray)):
            content_length = len(data)
        else:
            data = b''
            content_length = 0

        await self.send(b'HTTP/%s %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n%s\r\n%s' % (
            self._request.version,
            *self.get_status(),
            self.get_content_type(),
            content_length,
            self._header,
            data))

        await self.send(None)

    async def write(self, data, name='data', **kwargs):
        await self._write_cb(data=(name, data))
        await self.send(data, **kwargs)

    async def _on_write(self, **kwargs):
        return
