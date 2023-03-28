# Copyright (c) 2023 nggit

from datetime import datetime, timedelta
from urllib.parse import quote

from .response import Response

class HTTPResponse(Response):
    def __init__(self, request):
        super().__init__(request)

        self._header = [b'', bytearray()]
        self._request = request
        self._status = []
        self._content_type = []
        self._write_cb = None

        self._http_chunked = False

    @property
    def header(self):
        return self._header

    @header.setter
    def header(self, value):
        self._header[0] = value

    def append_header(self, value):
        self._header[1].extend(value)

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

        self._header[1].extend(cookie + b'\r\n')

    def set_header(self, name, value=''):
        if isinstance(name, str):
            name = name.encode(encoding='latin-1')

        if isinstance(value, str):
            value = value.encode(encoding='latin-1')

        self._header[1].extend(b'%s: %s\r\n' % (name, value))

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

    def close(self):
        self._request.http_keepalive = False
        super().close()

    async def end(self, data=b'', **kwargs):
        if self._header is None:
            await self.write(data, throttle=False)
        else:
            status = self.get_status()
            content_length = len(data)

            if content_length > 0 and (
                        self._request.method == b'HEAD' or status[0] in (204, 304) or 100 <= status[0] < 200
                    ):
                data = b''

            await self.send(b'HTTP/%s %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: %s\r\n%s\r\n%s' % (
                self._request.version,
                *status,
                self.get_content_type(),
                content_length,
                {True: b'keep-alive', False: b'close'}[self._request.http_keepalive],
                self._header[1],
                data), **kwargs)

            self._header = None

        await self.send(None)

    async def write(self, data, buffer_size=16 * 1024, **kwargs):
        kwargs['buffer_size'] = buffer_size

        if self._header is not None:
            if self._header[0] == b'':
                status = self.get_status()
                no_content = status[0] in (204, 304) or 100 <= status[0] < 200
                self._http_chunked = kwargs.get(
                    'chunked', self._request.version == b'1.1' and self._request.http_keepalive and not no_content
                )

                if self._http_chunked:
                    self.append_header(b'Transfer-Encoding: chunked\r\n')

                self._header[0] = b'HTTP/%s %d %s\r\n' % (self._request.version, *status)

                if no_content:
                    self.append_header(b'Connection: close\r\n\r\n')
                else:
                    if not self._http_chunked:
                        self._request.http_keepalive = False

                    self.append_header(b'Content-Type: %s\r\nConnection: keep-alive\r\n\r\n' %
                                       self.get_content_type())

                if self._request.method == b'HEAD' or no_content:
                    self._request.http_keepalive = False
                    data = None
                else:
                    self._request.protocol.set_watermarks(high=buffer_size * 4, low=buffer_size // 2)

            header = b''.join(self._header)

            if self._write_cb is not None:
                self._request.context.set('data', ('header', header))
                await self._write_cb()

            await self.send(header, throttle=False)

            self._header = None

        if self._write_cb is not None:
            self._request.context.set('data', ('body', data))
            await self._write_cb()

        if self._http_chunked and not self._request.http_upgrade and data is not None:
            await self.send(b'%X\r\n%s\r\n' % (len(data), data), **kwargs)
        else:
            await self.send(data, **kwargs)

    @property
    def http_chunked(self):
        return self._http_chunked

    @http_chunked.setter
    def http_chunked(self, value):
        self._http_chunked = value
