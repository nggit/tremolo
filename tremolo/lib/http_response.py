# Copyright (c) 2023 nggit

import asyncio
import os
import time

from base64 import urlsafe_b64encode as b64encode
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote_to_bytes

from tremolo.utils import parse_fields
from .http_exceptions import (
    HTTPException,
    BadRequest,
    InternalServerError,
    RangeNotSatisfiable,
    RequestTimeout,
    WebSocketException,
    WebSocketServerClosed
)
from .response import Response
from .websocket import WebSocket

KEEPALIVE_OR_CLOSE = {
    False: b'close',
    True: b'keep-alive'
}
UPGRADE_OR_KEEPALIVE = {
    False: b'keep-alive',
    True: b'upgrade'
}


class HTTPResponse(Response):
    __slots__ = ('http_chunked', '_headers')

    def __init__(self, request):
        super().__init__(request)

        self.http_chunked = None
        self._headers = {}

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

        key = name.lower()

        if key in self.headers:
            self.headers[key].append(name + b': ' + value)
        else:
            self.headers[key] = [name + b': ' + value]

    def set_header(self, name, value=''):
        if isinstance(name, str):
            name = name.encode('latin-1')

        if isinstance(value, str):
            value = value.encode('latin-1')

        if b'\n' in name or b'\n' in value:
            raise InternalServerError

        self.headers[name.lower()] = [name + b': ' + value]

    def set_base_headers(self):
        self.set_header(
            b'Date', self.request.server.globals.info['server_date']
        )

        if self.request.server.globals.info['server_name'] != b'':
            self.set_header(
                b'Server', self.request.server.globals.info['server_name']
            )

    def set_cookie(self, name, value='', *, expires=0, path='/', domain=None,
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
            b'%s=%s; expires=%s; max-age=%d; path=%s' %
            (name, value, date_expired, expires, path)
        )

        for k, v in ((b'domain', domain), (b'samesite', samesite)):
            if v:
                cookie.extend(b'; %s=%s' % (k, quote(v).encode('latin-1')))

        for k, v in ((secure, b'; secure'), (httponly, b'; httponly')):
            if k:
                cookie.extend(v)

        if b'\n' in cookie:
            raise InternalServerError

        self.append_header(b'Set-Cookie', cookie)

    def set_status(self, status=200, message=b'OK'):
        if isinstance(message, str):
            message = message.encode('latin-1')

        if not isinstance(status, int) or b'\n' in message:
            raise InternalServerError

        if b'_line' in self.headers:
            self.headers[b'_line'][1] = b'%d' % status
            self.headers[b'_line'][2] = message
        else:
            self.headers[b'_line'] = [b'HTTP/%s' % self.request.version,
                                      b'%d' % status,
                                      message]

    def get_status(self):
        try:
            _, status, message = self.headers.pop(b'_line')

            return (int(status), message)
        except KeyError:
            return (200, b'OK')

    def set_content_type(self, content_type=b'text/html; charset=utf-8'):
        if isinstance(content_type, str):
            content_type = content_type.encode('latin-1')

        if b'\n' in content_type:
            raise InternalServerError

        self.headers[b'content-type'] = [b'Content-Type: ' + content_type]

    def get_content_type(self):
        try:
            return self.headers.pop(b'content-type')[0][13:].strip(b' \t')
        except KeyError:
            return b'text/html; charset=utf-8'

    def close(self, keepalive=False):
        if not keepalive:
            # this will force the TCP connection to be terminated
            self.request.http_keepalive = False

        super().close()

    async def end(self, data=b'', *, keepalive=True, **kwargs):
        if self.headers_sent():
            await self.write(data)
        else:
            self.set_base_headers()

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
                b'Connection: %s\r\n%s\r\n\r\n%s' %
                (self.request.version,
                 *status,
                 self.get_content_type(),
                 content_length,
                 KEEPALIVE_OR_CLOSE[keepalive and self.request.http_keepalive],
                 b'\r\n'.join(b'\r\n'.join(v) for k, v in self.headers.items()
                              if k not in excludes),
                 data), **kwargs
            )
            self.headers_sent(True)

        self.close(keepalive=keepalive)

    async def write(self, data=None, *, chunked=None, buffer_size=16384,
                    **kwargs):
        kwargs['buffer_size'] = buffer_size

        if not self.headers_sent():
            self.set_base_headers()

            if b'connection' not in self.headers:
                # this block is executed when write() is called outside the
                # handler/middleware. e.g. ASGI server
                status = self.get_status()
                no_content = (status[0] in (204, 205, 304) or
                              100 <= status[0] < 200)

                if chunked is None:
                    if self.http_chunked is None:
                        self.http_chunked = (self.request.version == b'1.1' and
                                             not no_content)
                else:
                    self.http_chunked = chunked

                self.set_status(*status)

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
                        UPGRADE_OR_KEEPALIVE[status[0] in (101, 426)]
                    )
                else:
                    self.set_header(b'Connection', b'close')

                if self.request.method == b'HEAD' or no_content:
                    if status[0] not in (101, 426):
                        self.request.http_keepalive = False

                    data = None
                else:
                    self.request.server.set_watermarks(
                        high=buffer_size * 4,
                        low=kwargs.get('buffer_min_size', buffer_size // 2)
                    )

            await self.send(
                b' '.join(self.headers.pop(b'_line')) + b'\r\n' +
                b'\r\n'.join(b'\r\n'.join(v) for v in self.headers.values()) +
                b'\r\n\r\n'
            )
            self.headers_sent(True)

        if (self.http_chunked and not self.request.upgraded and
                data is not None):
            await self.send(b'%X\r\n%s\r\n' % (len(data), data), **kwargs)
        else:
            await self.send(data, **kwargs)

    async def sendfile(self, path, offset=0, count=-1, buffer_size=16384,
                       content_type=b'application/octet-stream', executor=None,
                       **kwargs):
        if isinstance(content_type, str):
            content_type = content_type.encode('latin-1')

        kwargs.setdefault('rate', self.request.server.options['download_rate'])
        kwargs['buffer_size'] = buffer_size
        loop = self.request.server.loop

        def run_sync(func, *args):
            if executor is None:
                return loop.run_in_executor(None, func, *args)

            fut = executor.submit(func, *args)

            if isinstance(fut, asyncio.Future):
                return fut

            return asyncio.wrap_future(fut, loop=loop)

        try:
            handle = self.request.server.context[path]
            await run_sync(handle.seek, offset)  # OSError on a negative offset
        except KeyError:
            handle = await run_sync(open, path, 'rb')
            self.request.server.context[path] = handle

            self.request.server.add_close_callback(handle.close)

        st = os.stat(path)
        file_size = st.st_size - offset

        if count > 0:
            file_size = min(count, file_size)

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
                _range = b';'.join(_range)

            ranges = []

            for key, _bytes in parse_fields(_range):
                if not (key == b'bytes' and _bytes):
                    raise BadRequest('bad range')

                try:
                    for v in parse_fields(_bytes, b',', split=None):
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
                    b'Content-Range', b'bytes %d-%d/%d' %
                    (start, end, file_size)
                )
                await run_sync(handle.seek, start)

                while size > 0:
                    data = await run_sync(handle.read, min(size, buffer_size))
                    await self.write(data, chunked=False, **kwargs)

                    size -= len(data)
            else:
                boundary = b'----Boundary%s' % b64encode(self.request.uid(24))

                self.set_content_type(
                    b'multipart/byteranges; boundary=%s' % boundary
                )

                for start, end, size in ranges:
                    await self.write(
                        b'--%s\r\nContent-Type: %s\r\n'
                        b'Content-Range: bytes %d-%d/%d\r\n\r\n' %
                        (boundary, content_type, start, end, file_size),
                        **kwargs
                    )
                    await run_sync(handle.seek, start)

                    while size > 0:
                        data = await run_sync(handle.read,
                                              min(size, buffer_size))
                        await self.write(data, **kwargs)

                        size -= len(data)

                    await self.write(b'\r\n', **kwargs)

                await self.write(b'--%s--\r\n' % boundary, **kwargs)
                await self.write(b'', **kwargs)
        else:
            if (b'if-modified-since' in self.request.headers and
                    self.request.headers[b'if-modified-since'] == mdate):
                self.set_status(304, b'Not Modified')
                await self.write()
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

    async def handle_exception(self, exc, data=None):
        if self.request.protocol is None or self.request.transport is None:
            return

        if self.request.transport.is_closing():  # maybe stuck?
            self.request.transport.abort()
            return

        if not isinstance(exc, asyncio.CancelledError):
            self.request.protocol.print_exception(
                exc, quote(unquote_to_bytes(self.request.path))
            )

        # WebSocket
        if isinstance(exc, WebSocketException):
            if isinstance(exc, WebSocketServerClosed):
                data = WebSocket.create_frame(
                    exc.code.to_bytes(2, byteorder='big'), opcode=8
                )
                await self.send(data)

            self.close(keepalive=True)
            return

        # HTTP
        if self.headers_sent():
            self.close()
            return

        if isinstance(exc, TimeoutError):
            exc = RequestTimeout(cause=exc)
        elif not isinstance(exc, HTTPException):
            exc = InternalServerError(cause=exc)

        self.headers.clear()
        self.set_status(exc.code, exc.message)
        self.set_content_type(exc.content_type)

        if not data:
            data = str(exc)

        if isinstance(data, str):
            data = data.encode(exc.encoding)

        await self.end(data, keepalive=False)
