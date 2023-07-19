# Copyright (c) 2023 nggit

import os
import time

from datetime import datetime, timedelta
from urllib.parse import quote

from .http_exception import (
    BadRequest, InternalServerError, RangeNotSatisfiable
)
from .response import Response


class HTTPResponse(Response):
    def __init__(self, request):
        super().__init__(request)

        self._header = [b'', bytearray()]
        self._request = request
        self._status = []
        self._content_type = []
        self._write_cb = None

        self.http_chunked = False

    @property
    def header(self):
        return self._header

    @header.setter
    def header(self, value):
        self._header[0] = value

    def append_header(self, value):
        self._header[1].extend(value)

    def set_cookie(
            self,
            name,
            value='',
            expires=0,
            path='/',
            domain=None,
            secure=False,
            httponly=False,
            samesite=None
            ):
        if isinstance(name, str):
            name = name.encode('latin-1')

        value = quote(value).encode('latin-1')
        date_expired = ((datetime.utcnow() + timedelta(seconds=expires))
                        .strftime('%a, %d %b %Y %H:%M:%S GMT')
                        .encode('latin-1'))
        path = quote(path).encode('latin-1')

        cookie = bytearray(
            b'Set-Cookie: %s=%s; expires=%s; max-age=%d; path=%s' % (
                name, value, date_expired, expires, path)
        )

        for k, v in ((b'domain', domain), (b'samesite', samesite)):
            if v:
                cookie.extend(b'; %s=%s' % (k, bytes(quote(v), 'latin-1')))

        for k, v in ((secure, b'; secure'), (httponly, b'; httponly')):
            if k:
                cookie.extend(v)

        if b'\n' in cookie:
            raise InternalServerError

        self._header[1].extend(cookie + b'\r\n')

    def set_header(self, name, value=''):
        if isinstance(name, str):
            name = name.encode('latin-1')

        if isinstance(value, str):
            value = value.encode('latin-1')

        if b'\n' in name or b'\n' in value:
            raise InternalServerError

        self._header[1].extend(b'%s: %s\r\n' % (name, value))

    def set_status(self, status=200, message=b'OK'):
        if isinstance(message, str):
            message = message.encode('latin-1')

        if not isinstance(status, int) or b'\n' in message:
            raise InternalServerError

        self._status.append((status, message))

    def get_status(self):
        try:
            return self._status.pop()
        except IndexError:
            return 200, b'OK'

    def set_content_type(self, content_type=b'text/html; charset=utf-8'):
        if isinstance(content_type, str):
            content_type = content_type.encode('latin-1')

        if b'\n' in content_type:
            raise InternalServerError

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
                        self._request.method == b'HEAD' or
                        status[0] in (204, 304) or 100 <= status[0] < 200
                    ):
                data = b''

            await self.send(
                b'HTTP/%s %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                b'Connection: %s\r\n%s\r\n%s' % (
                    self._request.version,
                    *status,
                    self.get_content_type(),
                    content_length,
                    {True: b'keep-alive',
                        False: b'close'}[self._request.http_keepalive],
                    self._header[1],
                    data), **kwargs
            )

            self._header = None

        await self.send(None)

    async def write(self, data, buffer_size=16 * 1024, **kwargs):
        kwargs['buffer_size'] = buffer_size

        if self._header is not None:
            if self._header[0] == b'':
                status = self.get_status()
                no_content = status[0] in (204, 304) or 100 <= status[0] < 200
                self.http_chunked = kwargs.get(
                    'chunked', self._request.version == b'1.1' and
                    self._request.http_keepalive and not no_content
                )

                if self.http_chunked:
                    self.append_header(b'Transfer-Encoding: chunked\r\n')

                self._header[0] = b'HTTP/%s %d %s\r\n' % (
                    self._request.version, *status)

                if no_content:
                    self.append_header(b'Connection: close\r\n\r\n')
                else:
                    if not self.http_chunked and not (
                            self._request.version == b'1.1' and
                            b'range' in self._request.headers):
                        self._request.http_keepalive = False

                    if status[0] == 101:
                        self._request.http_upgrade = True

                    self.append_header(
                        b'Content-Type: %s\r\nConnection: %s\r\n\r\n' % (
                            self.get_content_type(),
                            {False: b'keep-alive',
                                True: b'upgrade'}[status[0] in (101, 426)])
                    )

                if self._request.method == b'HEAD' or no_content:
                    self._request.http_keepalive = False
                    data = None
                else:
                    self._request.protocol.set_watermarks(high=buffer_size * 4,
                                                          low=buffer_size // 2)

            header = b''.join(self._header)

            if self._write_cb is not None:
                self._request.context.set('data', ('header', header))
                await self._write_cb()

            await self.send(header, throttle=False)

            self._header = None

        if self._write_cb is not None:
            self._request.context.set('data', ('body', data))
            await self._write_cb()

        if (self.http_chunked and not self._request.http_upgrade and
                data is not None):
            await self.send(b'%X\r\n%s\r\n' % (len(data), data), **kwargs)
        else:
            await self.send(data, **kwargs)

    async def sendfile(
            self,
            path,
            buffer_size=16384,
            content_type=b'application/octet-stream'
            ):
        try:
            handle = self._request.context._sendfile_handle
        except AttributeError:
            handle = open(path, 'rb')
            self._request.context._sendfile_handle = handle

            self._request.context.tasks.append(
                self._request.context._sendfile_handle.close
            )

        file_size = os.stat(path).st_size
        mtime = os.path.getmtime(path)
        mdate = time.strftime('%a, %d %b %Y %H:%M:%S GMT',
                              time.gmtime(mtime)).encode('latin-1')

        if (self._request.version == b'1.1' and
                b'range' in self._request.headers):
            if (b'if-range' in self._request.headers and
                    self._request.headers[b'if-range'] != mdate):
                self.set_content_type(content_type)
                self.set_header(b'Last-Modified', mdate)
                self.set_header(b'Content-Length', b'%d' % file_size)
                self.set_header(b'Accept-Ranges', b'bytes')

                data = True

                while data:
                    data = handle.read(buffer_size)

                    await self.write(data, chunked=False)

                await self.send(None)
                return

            _range = self._request.headers[b'range']

            if isinstance(_range, list):
                for v in _range:
                    if not v.startswith(b'bytes='):
                        raise BadRequest('bad range')

                _range = b','.join(_range)
            else:
                if not _range.startswith(b'bytes='):
                    raise BadRequest('bad range')

            ranges = []

            try:
                for v in _range.replace(b'bytes=', b'').split(b','):
                    v = v.strip()

                    if v.startswith(b'-'):
                        start = file_size + int(v)

                        if start < 0:
                            raise RangeNotSatisfiable

                        ranges.append(
                            (start, file_size - 1, file_size - start)
                        )
                    elif v.endswith(b'-'):
                        start = int(v[:-1])

                        if start >= file_size:
                            raise RangeNotSatisfiable

                        ranges.append(
                            (start, file_size - 1, file_size - start)
                        )
                    else:
                        start, end = v.split(b'-')
                        start = int(start)
                        end = int(end)

                        if end == 0:
                            end = start

                        if start > end or end >= file_size:
                            raise RangeNotSatisfiable

                        ranges.append((start, end, end - start + 1))
            except ValueError as exc:
                raise BadRequest('bad range', cause=exc)

            self.set_status(206, b'Partial Content')

            if len(ranges) == 1:
                start, end, size = ranges[0]

                self.set_content_type(content_type)
                self.set_header(b'Content-Length', b'%d' % size)
                self.set_header(
                    b'Content-Range', b'bytes %d-%d/%d' % (
                        start, end, file_size)
                )

                handle.seek(start)
                await self.write(handle.read(size), chunked=False)
            else:
                ip, port = self._request.client
                boundary = b'----Boundary%x%x' % (hash(ip), port)

                self.set_content_type(
                    b'multipart/byteranges; boundary=%s' % boundary
                )

                for start, end, size in ranges:
                    await self.write(
                        b'--%s\r\nContent-Type: %s\r\n'
                        b'Content-Range: bytes %d-%d/%d\r\n\r\n' % (
                            boundary, content_type, start, end, file_size)
                    )

                    handle.seek(start)
                    await self.write(b'%s\r\n' % handle.read(size))

                await self.write(b'--%s--\r\n' % boundary)
                await self.write(b'')
        else:
            if (b'if-modified-since' in self._request.headers and
                    self._request.headers[b'if-modified-since'] == mdate):
                self.set_status(304, b'Not Modified')
                await self.write(None)
                return

            self.set_content_type(content_type)
            self.set_header(b'Last-Modified', mdate)
            self.set_header(b'Content-Length', b'%d' % file_size)

            if self._request.version == b'1.1':
                self.set_header(b'Accept-Ranges', b'bytes')

            data = True

            while data:
                data = handle.read(buffer_size)

                await self.write(data, chunked=False)

        await self.send(None)
