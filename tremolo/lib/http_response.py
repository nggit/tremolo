# Copyright (c) 2023 nggit

import asyncio
import os
import time

from base64 import urlsafe_b64encode as b64encode
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .http_exceptions import (
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
    __slots__ = ('_headers',
                 'http_chunked',
                 'request',
                 '_status',
                 '_content_type')

    def __init__(self, request):
        super().__init__(request)

        self._headers = {}
        self.http_chunked = False

        self.request = request
        self._status = []
        self._content_type = []

    @property
    def headers(self):
        if self._headers is None:
            raise InternalServerError('headers already sent')

        return self._headers

    def headers_sent(self, sent=False):
        if sent:
            self._headers = None

        return self._headers is None

    def append_header(self, name, value):
        if isinstance(name, str):
            name = name.encode('latin-1')

        if isinstance(value, str):
            value = value.encode('latin-1')

        _name = name.lower()

        if _name in self.headers:
            self.headers[_name].append(name + b': ' + value)
        else:
            self.headers[_name] = [name + b': ' + value]

    def set_base_header(self):
        if self.headers_sent() or self.headers:
            return

        self.set_header(
            b'Date',
            self.request.protocol.globals.info['server_date']
        )
        self.set_header(
            b'Server',
            self.request.protocol.globals.info['server_name']
        )

    def set_cookie(self, name, value='', expires=0, path='/', domain=None,
                   secure=False, httponly=False, samesite=None):
        if isinstance(name, str):
            name = name.encode('latin-1')

        value = quote(value).encode('latin-1')
        date_expired = (
            (datetime.now(timezone.utc) + timedelta(seconds=expires))
            .strftime('%a, %d %b %Y %H:%M:%S GMT')
            .encode('latin-1')
        )
        path = quote(path).encode('latin-1')

        cookie = bytearray(
            b'%s=%s; expires=%s; max-age=%d; path=%s' % (
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

        self.append_header(b'Set-Cookie', cookie)

    def set_header(self, name, value=''):
        if isinstance(name, str):
            name = name.encode('latin-1')

        if isinstance(value, str):
            value = value.encode('latin-1')

        if b'\n' in name or b'\n' in value:
            raise InternalServerError

        self.headers[name.lower()] = [name + b': ' + value]

    def set_status(self, status=200, message=b'OK'):
        if isinstance(message, str):
            message = message.encode('latin-1')

        if not isinstance(status, int) or b'\n' in message:
            raise InternalServerError

        if b'_line' in self.headers:
            self.headers[b'_line'][1] = b'%d' % status
            self.headers[b'_line'][2] = message
        else:
            self._status.append((status, message))

    def get_status(self):
        if b'_line' in self.headers:
            _, status, message = self.headers.pop(b'_line')
            return int(status), message

        try:
            return self._status.pop()
        except IndexError:
            return 200, b'OK'

    def set_content_type(self, content_type=b'text/html; charset=utf-8'):
        if isinstance(content_type, str):
            content_type = content_type.encode('latin-1')

        if b'\n' in content_type:
            raise InternalServerError

        if b'content-type' in self.headers:
            self.headers[b'content-type'] = [b'Content-Type: ' + content_type]
        else:
            self._content_type.append(content_type)

    def get_content_type(self):
        if b'content-type' in self.headers:
            return self.headers.pop(b'content-type')[0][13:].lstrip()

        try:
            return self._content_type.pop()
        except IndexError:
            return b'text/html; charset=utf-8'

    def close(self, keepalive=False):
        if not keepalive:
            # this will force the TCP connection to be terminated
            self.request.http_keepalive = False

        super().close()

    async def send_continue(self):
        if self.request.http_continue:
            if (self.request.content_length >
                    self.request.protocol.options['client_max_body_size']):
                raise ExpectationFailed

            await self.send(
                b'HTTP/%s 100 Continue\r\n\r\n' % self.request.version,
                throttle=False
            )
            self.close(keepalive=True)

    async def end(self, data=b'', keepalive=True, **kwargs):
        if self.headers_sent():
            await self.write(data, throttle=False)
        else:
            self.set_base_header()

            status = self.get_status()
            content_length = len(data)

            if content_length > 0 and (
                        self.request.method == b'HEAD' or
                        status[0] in (204, 205, 304) or 100 <= status[0] < 200
                    ):
                data = b''

            excludes = (b'connection', b'content-length', b'transfer-encoding')

            await self.send(
                b'HTTP/%s %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                b'Connection: %s\r\n%s\r\n\r\n%s' % (
                    self.request.version,
                    *status,
                    self.get_content_type(),
                    content_length,
                    KEEPALIVE_OR_CLOSE[
                        keepalive and self.request.http_keepalive],
                    b'\r\n'.join(
                        b'\r\n'.join(v) for k, v in self.headers.items() if
                        k not in excludes),
                    data), throttle=False, **kwargs
            )

            self.headers_sent(True)

        self.close(keepalive=keepalive)

    async def write(self, data, chunked=None, buffer_size=16 * 1024, **kwargs):
        kwargs['buffer_size'] = buffer_size

        if not self.headers_sent():
            if b'_line' not in self.headers:
                # this block is executed when write() is called outside the
                # handler/middleware. e.g. ASGI server
                self.set_base_header()

                status = self.get_status()
                no_content = (status[0] in (204, 205, 304) or
                              100 <= status[0] < 200)

                if chunked is None:
                    self.http_chunked = (self.request.version == b'1.1' and
                                         not no_content)
                else:
                    self.http_chunked = chunked

                self.headers[b'_line'] = [b'HTTP/%s' % self.request.version,
                                          b'%d' % status[0],
                                          status[1]]

                if not no_content:
                    self.set_header(b'Content-Type', self.get_content_type())

                if self.http_chunked:
                    self.set_header(b'Transfer-Encoding', b'chunked')

                if self.request.http_keepalive:
                    if status[0] == 101:
                        self.request.upgraded = True
                    elif not (self.http_chunked or
                              b'content-length' in self.headers):
                        # no chunk, no close, no size.
                        # Assume close to signal end
                        self.request.http_keepalive = False

                    self.set_header(
                        b'Connection',
                        KEEPALIVE_OR_UPGRADE[status[0] in (101, 426)]
                    )
                else:
                    self.set_header(b'Connection', b'close')

                if self.request.method == b'HEAD' or no_content:
                    if status[0] not in (101, 426):
                        self.request.http_keepalive = False

                    data = None
                else:
                    self.request.protocol.set_watermarks(
                        high=buffer_size * 4,
                        low=kwargs.get('buffer_min_size', buffer_size // 2)
                    )

            await self.send(
                b' '.join(self.headers.pop(b'_line')) + b'\r\n' +
                b'\r\n'.join(b'\r\n'.join(v) for v in self.headers.values()) +
                b'\r\n\r\n', throttle=False
            )
            self.headers_sent(True)

        if (self.http_chunked and not self.request.upgraded and
                data is not None):
            await self.send(b'%X\r\n%s\r\n' % (len(data), data), **kwargs)
        else:
            await self.send(data, **kwargs)

    async def sendfile(self, path, file_size=None, buffer_size=16 * 1024,
                       content_type=b'application/octet-stream', executor=None,
                       **kwargs):
        if isinstance(content_type, str):
            content_type = content_type.encode('latin-1')

        kwargs['buffer_size'] = buffer_size
        loop = self.request.protocol.loop

        def run_sync(func, *args):
            if executor is None:
                return loop.run_in_executor(None, func, *args)

            fut = executor.submit(func, *args)

            if isinstance(fut, asyncio.Future):
                return fut

            return asyncio.wrap_future(fut, loop=loop)

        try:
            handle = self.request.protocol.context.RESPONSE_SENDFILE_HANDLE
            await run_sync(handle.seek, 0)
        except AttributeError:
            handle = await run_sync(open, path, 'rb')
            self.request.protocol.context.RESPONSE_SENDFILE_HANDLE = handle

            self.request.protocol.add_close_callback(
                self.request.protocol.context.RESPONSE_SENDFILE_HANDLE.close
            )

        st = os.stat(path)

        if not file_size:
            file_size = st.st_size

        mdate = time.strftime('%a, %d %b %Y %H:%M:%S GMT',
                              time.gmtime(st.st_mtime)).encode('latin-1')

        if self.request.version == b'1.1' and b'range' in self.request.headers:
            if (b'if-range' in self.request.headers and
                    self.request.headers[b'if-range'] != mdate):
                self.set_content_type(content_type)
                self.set_header(b'Last-Modified', mdate)
                self.set_header(b'Content-Length', b'%d' % file_size)
                self.set_header(b'Accept-Ranges', b'bytes')

                data = True

                while data:
                    data = await run_sync(handle.read, buffer_size)

                    await self.write(data, chunked=False, **kwargs)

                self.close(keepalive=True)
                return

            _range = self.request.headers[b'range']

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
                for v in _range.replace(b'bytes=', b'').split(b',', 100):
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
                        start, end = v.split(b'-', 1)
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
                await run_sync(handle.seek, start)

                while size > 0:
                    await self.write(
                        await run_sync(handle.read, min(size, buffer_size)),
                        chunked=False, **kwargs
                    )
                    size -= buffer_size
            else:
                boundary = b'----Boundary%s' % b64encode(self.request.uid(24))

                self.set_content_type(
                    b'multipart/byteranges; boundary=%s' % boundary
                )

                for start, end, size in ranges:
                    await self.write(
                        b'--%s\r\nContent-Type: %s\r\n'
                        b'Content-Range: bytes %d-%d/%d\r\n\r\n' % (
                            boundary, content_type, start, end, file_size),
                        **kwargs
                    )
                    await run_sync(handle.seek, start)

                    while size > 0:
                        await self.write(
                            await run_sync(handle.read,
                                           min(size, buffer_size)),
                            **kwargs
                        )
                        size -= buffer_size

                    await self.write(b'\r\n', **kwargs)

                await self.write(b'--%s--\r\n' % boundary, **kwargs)
                await self.write(b'', **kwargs)
        else:
            if (b'if-modified-since' in self.request.headers and
                    self.request.headers[b'if-modified-since'] == mdate):
                self.set_status(304, b'Not Modified')
                await self.write(None)
                return

            self.set_content_type(content_type)
            self.set_header(b'Last-Modified', mdate)
            self.set_header(b'Content-Length', b'%d' % file_size)

            if self.request.version == b'1.1':
                self.set_header(b'Accept-Ranges', b'bytes')

            data = True

            while data:
                data = await run_sync(handle.read, buffer_size)

                await self.write(data, chunked=False, **kwargs)

        self.close(keepalive=True)
