# Copyright (c) 2023 nggit

import os
import time

from datetime import datetime, timedelta
from urllib.parse import quote

from .http_exception import (
    BadRequest, ExpectationFailed, InternalServerError, RangeNotSatisfiable
)
from .response import Response

KEEPALIVE_OR_CLOSE = {
    True: b'keep-alive',
    False: b'close'
}
KEEPALIVE_OR_UPGRADE = {
    False: b'keep-alive',
    True: b'upgrade'
}


class HTTPResponse(Response):
    __slots__ = ('_header',
                 '_request',
                 '_status',
                 '_content_type',
                 '_write_cb',
                 'http_chunked')

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

    def headers_sent(self, sent=False):
        if sent:
            self._header = None

        return self._header is None

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

    def close(self, keepalive=False, delay=None):
        if not keepalive:
            self._request.http_keepalive = False

        if delay is None or delay < 1:
            super().close()
        else:
            self._request.protocol.loop.call_at(
                self._request.protocol.loop.time() + delay,
                super().close
            )

    async def send_continue(self):
        if self._request.http_continue:
            if (self._request.content_length >
                    self._request.protocol.options['client_max_body_size']):
                raise ExpectationFailed

            await self.send(b'HTTP/%s 100 Continue\r\n\r\n' %
                            self._request.version)

    async def end(self, data=b'', **kwargs):
        if self.headers_sent():
            await self.write(data, throttle=False)
        else:
            status = self.get_status()
            content_length = len(data)

            if content_length > 0 and (
                        self._request.method == b'HEAD' or
                        status[0] in (204, 205, 304) or 100 <= status[0] < 200
                    ):
                data = b''

            await self.send(
                b'HTTP/%s %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                b'Connection: %s\r\n%s\r\n%s' % (
                    self._request.version,
                    *status,
                    self.get_content_type(),
                    content_length,
                    KEEPALIVE_OR_CLOSE[self._request.http_keepalive],
                    self._header[1],
                    data), **kwargs
            )

            self.headers_sent(True)

        self.close(keepalive=True)

    async def write(self, data, buffer_size=16 * 1024, **kwargs):
        kwargs['buffer_size'] = buffer_size

        if not self.headers_sent():
            if self._header[0] == b'':
                status = self.get_status()
                no_content = (status[0] in (204, 205, 304) or
                              100 <= status[0] < 200)
                self.http_chunked = kwargs.get(
                    'chunked', self._request.version == b'1.1' and
                    self._request.http_keepalive and not no_content
                )

                if self.http_chunked:
                    self.append_header(b'Transfer-Encoding: chunked\r\n')

                self._header[0] = b'HTTP/%s %d %s\r\n' % (
                    self._request.version, *status)

                if no_content and status[0] not in (101, 426):
                    self.append_header(b'Connection: close\r\n\r\n')
                else:
                    if not self.http_chunked and not (
                            self._request.version == b'1.1' and (
                                status[0] in (101, 426) or
                                b'range' in self._request.headers)):
                        self._request.http_keepalive = False

                    if status[0] == 101:
                        self._request.upgraded = True
                    elif not no_content:
                        self.append_header(b'Content-Type: %s\r\n' %
                                           self.get_content_type())

                    self.append_header(
                        b'Connection: %s\r\n\r\n' % KEEPALIVE_OR_UPGRADE[
                            status[0] in (101, 426)]
                    )

                if self._request.method == b'HEAD' or no_content:
                    if status[0] not in (101, 426):
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

            self.headers_sent(True)

        if self._write_cb is not None:
            self._request.context.set('data', ('body', data))
            await self._write_cb()

        if (self.http_chunked and not self._request.upgraded and
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
            handle = self._request.context.RESPONSE_SENDFILE_HANDLE
        except AttributeError:
            handle = open(path, 'rb')
            self._request.context.RESPONSE_SENDFILE_HANDLE = handle

            self._request.context.tasks.append(
                self._request.context.RESPONSE_SENDFILE_HANDLE.close
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

                self.close(keepalive=True)
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
                raise BadRequest('bad range') from exc

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
                client = self._request.client

                if client is None:
                    fileno = self._request.socket.fileno()
                    client = (str(fileno), fileno)

                ip, port = client
                boundary = b'----Boundary%x%x%x%x' % (hash(ip),
                                                      port,
                                                      os.getpid(),
                                                      int.from_bytes(
                                                          os.urandom(4),
                                                          byteorder='big'))

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

        self.close(keepalive=True)
