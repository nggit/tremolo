# Copyright (c) 2023 nggit

import os
import time

from urllib.parse import parse_qs, unquote

from tremolo.utils import parse_fields
from .http_exceptions import BadRequest, PayloadTooLarge
from .request import Request


class HTTPRequest(Request):
    __slots__ = ('_ip',
                 '_scheme',
                 'header',
                 'headers',
                 'is_valid',
                 'host',
                 'method',
                 'url',
                 'path',
                 'query_string',
                 'version',
                 'content_length',
                 'transfer_encoding',
                 'http_continue',
                 'http_keepalive',
                 '_upgraded',
                 '_body',
                 '_eof',
                 '_read_instance',
                 '_read_buf')

    def __init__(self, protocol, header):
        super().__init__(protocol)

        self._ip = None
        self._scheme = None
        self.header = header
        self.headers = header.headers.copy()
        self.is_valid = header.is_valid
        self.host = header.gethost()

        if isinstance(self.host, list):
            self.host = self.host[0]

        self.method = header.getmethod().upper()
        self.url = header.geturl()
        self.path, _, self.query_string = self.url.partition(b'?')
        self.version = header.getversion()

        if self.version != b'1.0':
            self.version = b'1.1'

        self.content_length = -1
        self.transfer_encoding = b'none'
        self.http_continue = False
        self.http_keepalive = False
        self._upgraded = False
        self._body = bytearray()
        self._eof = False
        self._read_instance = None
        self._read_buf = bytearray()

    @property
    def ip(self):
        if not self._ip:
            ip = self.headers.get(b'x-forwarded-for', b'')

            if isinstance(ip, list):
                ip = ip[0]

            ip = ip.strip()

            if ip == b'' and self.client is not None:
                self._ip = self.client[0].encode('utf-8')
            else:
                self._ip = ip[:(ip + b',').find(b',')]

        return self._ip

    @property
    def scheme(self):
        if not self._scheme:
            scheme = self.headers.get(b'x-forwarded-proto', b'').strip()

            if scheme == b'' and self.is_secure:
                self._scheme = b'https'
            else:
                self._scheme = scheme or b'http'

        return self._scheme

    @property
    def content_type(self):
        # don't lower() content-type, as it may contain a boundary
        return self.headers.get(b'content-type', b'application/octet-stream')

    @property
    def upgraded(self):
        return self._upgraded

    @upgraded.setter
    def upgraded(self, value):
        self.clear_body()
        self._upgraded = value

    @property
    def has_body(self):
        return (b'content-length' in self.headers or
                b'transfer-encoding' in self.headers)

    def uid(self, length=32):
        if self.client is None:
            port = self.socket.fileno()
        else:
            port = self.client[1]  # 0 - 65535

        prefix = (
            int.to_bytes((port << 16) | (os.getpid() & 0xffff),
                         4, byteorder='big') +
            int(time.time() * 1e7).to_bytes(8, byteorder='big')
        )  # 12 Bytes

        return prefix + os.urandom(max(4, length - len(prefix)))

    def clear_body(self):
        del self._body[:]
        del self._read_buf[:]
        super().clear_body()

    async def body(self, raw=False):
        async for data in self.stream(raw=raw):
            self._body.extend(data)

        return self._body

    def read(self, size=-1):
        return self.recv(size=size, raw=False)

    def eof(self):
        return self._eof and self._read_buf == b''

    async def recv(self, size=-1, raw=True):
        if size == 0 or self.eof():
            return b''

        if self._read_instance is None:
            self._read_instance = self.stream(raw=raw)

        if size == -1:
            return bytes(await self._read_instance.__anext__())

        if len(self._read_buf) < size:
            async for data in self._read_instance:
                self._read_buf.extend(data)

                if len(self._read_buf) >= size:
                    break

        buf = self._read_buf[:size]
        del self._read_buf[:size]
        return bytes(buf)

    async def stream(self, raw=False):
        if self._eof:
            return

        if self.http_continue:
            self.protocol.send_continue()

        if not raw and b'chunked' in self.transfer_encoding:
            buf = bytearray()
            agen = super().recv()
            paused = False
            unread_bytes = 0

            while True:
                if not paused:
                    try:
                        buf.extend(await agen.__anext__())
                    except StopAsyncIteration as exc:
                        if b'\r\n\r\n' not in buf:
                            del buf[:]
                            raise BadRequest(
                                'bad chunked encoding: incomplete read'
                            ) from exc

                if unread_bytes > 0:
                    data = buf[:unread_bytes]

                    yield data
                    del buf[:unread_bytes]

                    unread_bytes -= len(data)

                    if unread_bytes > 0:
                        continue

                    paused = True
                    del buf[:2]
                else:
                    i = buf.find(b'\r\n')

                    if i == -1:
                        if len(buf) > self.protocol.options['buffer_size'] * 4:
                            del buf[:]
                            raise BadRequest(
                                'bad chunked encoding: no chunk size'
                            )

                        paused = False
                        continue

                    try:
                        chunk_size = int(b'0x' + buf[:i].split(b';', 1)[0], 16)
                    except ValueError as exc:
                        del buf[:]
                        raise BadRequest('bad chunked encoding') from exc

                    if chunk_size < 1:
                        break

                    data = buf[i + 2:i + 2 + chunk_size]
                    unread_bytes = chunk_size - len(data)

                    yield data

                    if unread_bytes > 0:
                        paused = False
                        del buf[:]
                    else:
                        paused = True
                        del buf[:chunk_size + i + 4]
        else:
            if (self.content_length >
                    self.protocol.options['client_max_body_size']):
                raise PayloadTooLarge

            async for data in super().recv():
                if -1 < self.content_length < self.body_consumed:
                    # pipelining is not yet supported on a request with a body
                    self.protocol.logger.info('Content-Length mismatch')
                    yield data[:self.content_length - self.body_consumed]
                else:
                    yield data

        self._eof = True

    @property
    def params(self):
        return self.context

    @property
    def query(self):
        try:
            return self.params['query']
        except KeyError:
            self.params['query'] = {}

            if self.query_string != b'':
                self.params['query'] = parse_qs(
                    self.query_string.decode('latin-1'), max_num_fields=100
                )

            return self.params['query']

    @property
    def cookies(self):
        try:
            return self.params['cookies']
        except KeyError:
            self.params['cookies'] = {}

            if b'cookie' in self.headers:
                if isinstance(self.headers[b'cookie'], list):
                    data = b';'.join(self.headers[b'cookie']).decode('latin-1')
                else:
                    data = self.headers[b'cookie'].decode('latin-1')

                for name, value in parse_fields(data):
                    if name in self.params['cookies']:
                        self.params['cookies'][name].append(unquote(value))
                    else:
                        self.params['cookies'][name] = [unquote(value)]

            return self.params['cookies']

    async def form(self, max_size=8 * 1048576, max_fields=100):
        try:
            return self.params['post']
        except KeyError as exc:
            self.params['post'] = {}

            if (b'application/x-www-form-urlencoded' in
                    self.content_type.lower()):
                async for data in self.stream():
                    self._body.extend(data)

                    if self.body_size > max_size:
                        raise ValueError('form size limit reached') from exc

                if 2 < self.body_size <= max_size:
                    self.params['post'] = parse_qs(
                        self._body.decode('latin-1'),
                        max_num_fields=max_fields
                    )

            return self.params['post']

    async def files(self, max_files=1024, max_file_size=100 * 1048576):
        if self.eof():
            return

        for name, value in parse_fields(self.content_type.decode('latin-1')):
            if name == 'boundary' and value:
                break
        else:
            raise BadRequest('missing boundary')

        boundary = value.encode('latin-1')
        boundary_size = len(boundary)
        header = None
        body = bytearray()

        header_size = 0
        body_size = 0
        content_length = 0
        part = {}  # represents a file received in a multipart request
        paused = False

        if self._read_instance is None:
            self._read_instance = self.stream()

        while max_files > 0 and not self._read_buf.startswith(b'--%s--' %
                                                              boundary):
            data = b''

            if not paused:
                try:
                    data = await self._read_instance.__anext__()
                except StopAsyncIteration as exc:
                    if header_size == 1 or body_size == -1:
                        del body[:]
                        raise BadRequest(
                            'malformed multipart/form-data: incomplete read'
                        ) from exc

            if header is None:
                self._read_buf.extend(data)
                header_size = self._read_buf.find(b'\r\n\r\n') + 2

                if header_size == 1:
                    if len(self._read_buf) > 8192:
                        raise BadRequest(
                            'malformed multipart/form-data: header too large'
                        )

                    paused = False
                else:
                    body.extend(self._read_buf[header_size + 2:])

                    # use find() instead of startswith() to ignore the preamble
                    if self._read_buf.find(b'--%s\r\n' % boundary,
                                           0, header_size) != -1:
                        header = self.header.parse(
                            self._read_buf, header_size=header_size
                        ).headers

                        if b'content-disposition' in header:
                            for name, value in parse_fields(
                                    header[b'content-disposition']
                                    .decode('latin-1')):
                                part[name] = value

                        if b'content-length' in header:
                            content_length = int(
                                b'+' + header[b'content-length']
                            )
                            part['length'] = content_length

                        if b'content-type' in header:
                            part['type'] = header[
                                           b'content-type'].decode('latin-1')
                    else:
                        header = {}

                continue

            body.extend(data)
            body_size = body.find(b'\r\n--%s' % boundary, content_length)

            if body_size == -1:
                if len(body) >= max_file_size > boundary_size + 4:
                    sub_part = part.copy()
                    sub_part['data'] = body[:-boundary_size - 4]
                    sub_part['eof'] = False
                    yield sub_part

                    content_length = max(
                        content_length - (len(body) - boundary_size - 4), 0
                    )
                    del body[:-boundary_size - 4]

                paused = False
                continue

            part['data'] = body[:body_size]
            part['eof'] = True
            yield part

            self._read_buf[:] = body[body_size + 2:]
            header = None
            content_length = 0
            part = {}
            paused = True
            max_files -= 1

            del body[:]
