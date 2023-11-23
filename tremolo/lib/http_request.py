# Copyright (c) 2023 nggit

from urllib.parse import parse_qs, parse_qsl

from .http_exception import BadRequest, PayloadTooLarge
from .request import Request


class HTTPRequest(Request):
    __slots__ = ('_socket',
                 '_client',
                 '_ip',
                 '_is_secure',
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
                 'content_type',
                 'transfer_encoding',
                 '_body',
                 'http_continue',
                 'http_keepalive',
                 '_upgraded',
                 'params',
                 '_eof',
                 '_read_instance',
                 '_read_buf')

    def __init__(self, protocol, header):
        super().__init__(protocol)

        self._socket = None
        self._client = None
        self._ip = None
        self._is_secure = None
        self.header = header
        self.headers = header.headers
        self.is_valid = header.is_valid_request
        self.host = header.gethost()

        if isinstance(self.host, list):
            self.host = self.host[0]

        self.method = header.getmethod().upper()
        self.url = header.geturl()
        path_size = self.url.find(b'?')

        if path_size == -1:
            self.path = self.url
            self.query_string = b''
        else:
            self.path = self.url[:path_size]
            self.query_string = self.url[path_size + 1:]

        self.version = header.getversion()

        if self.version != b'1.0':
            self.version = b'1.1'

        self.content_length = -1
        self.content_type = b'application/octet-stream'
        self.transfer_encoding = b'none'
        self._body = bytearray()
        self.http_continue = False
        self.http_keepalive = False
        self._upgraded = False
        self.params = {}

        self._eof = False
        self._read_instance = None
        self._read_buf = bytearray()

    @property
    def socket(self):
        if not self._socket:
            self._socket = self.transport.get_extra_info('socket')

        return self._socket

    @property
    def client(self):
        if not self._client:
            try:
                self._client = self.socket.getpeername()[:2]
            except TypeError:
                pass

        return self._client

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
    def is_secure(self):
        if self._is_secure is None:
            self._is_secure = self.transport.get_extra_info('sslcontext') is not None  # noqa: E501

        return self._is_secure

    @property
    def has_body(self):
        return (b'content-length' in self.headers or
                b'transfer-encoding' in self.headers)

    def clear_body(self):
        del self._body[:]
        del self._read_buf[:]
        super().clear_body()

    async def body(self, raw=False):
        async for data in self.stream(raw=raw):
            self._body.extend(data)

        return self._body

    def read(self, size=None):
        if size is None:
            return self.stream()

        return self.recv(size=size, raw=False)

    def eof(self):
        return self._eof and self._read_buf == b''

    async def recv(self, size=-1, raw=True):
        if size == 0 or self.eof():
            return bytearray()

        if size == -1:
            return await self.body(raw=raw)

        if self._read_instance is None:
            self._read_instance = self.stream(raw=raw)

        if len(self._read_buf) < size:
            async for data in self._read_instance:
                self._read_buf.extend(data)

                if len(self._read_buf) >= size:
                    break

        buf = self._read_buf[:size]
        del self._read_buf[:size]
        return buf

    async def stream(self, raw=False):
        if self._eof:
            return

        if self.http_continue:
            await self.protocol.response.send_continue()

        if not raw and b'chunked' in self.transfer_encoding:
            buf = bytearray()
            agen = super().recv()
            paused = False
            unread_bytes = 0

            while not buf.startswith(b'0\r\n'):
                if not paused:
                    try:
                        buf.extend(await agen.__anext__())
                    except StopAsyncIteration:
                        if b'0\r\n' not in buf:
                            del buf[:]
                            raise BadRequest(
                                'bad chunked encoding: incomplete read'
                            )

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
                        chunk_size = int(buf[:i].split(b';', 1)[0], 16)
                    except ValueError:
                        del buf[:]
                        raise BadRequest('bad chunked encoding')

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
                yield data

        self._eof = True

    @property
    def upgraded(self):
        return self._upgraded

    @upgraded.setter
    def upgraded(self, value):
        self.clear_body()
        self._upgraded = value

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
                    self.params['cookies'] = parse_qs(
                        b'; '.join(self.headers[b'cookie'])
                        .replace(b'; ', b'&').replace(b';', b'&')
                        .decode('latin-1'),
                        max_num_fields=100
                    )
                else:
                    self.params['cookies'] = parse_qs(
                        self.headers[b'cookie'].replace(b'; ', b'&')
                        .replace(b';', b'&').decode('latin-1'),
                        max_num_fields=100
                    )

            return self.params['cookies']

    async def form(self, limit=8 * 1048576, max_fields=100):
        try:
            return self.params['post']
        except KeyError:
            self.params['post'] = {}

            if (b'application/x-www-form-urlencoded' in
                    self.content_type.lower()):
                async for data in self.stream():
                    self._body.extend(data)

                    if self.body_size > limit:
                        break

                if 2 < self.body_size <= limit:
                    self.params['post'] = parse_qs(
                        self._body.decode('latin-1'),
                        max_num_fields=max_fields
                    )

            return self.params['post']

    async def files(self, limit=1024):
        if self.eof():
            return

        ct = parse_qs(
            self.content_type.replace(b'; ', b'&').replace(b';', b'&')
            .decode('latin-1'),
            max_num_fields=100
        )

        try:
            boundary = ct['boundary'][-1].encode('latin-1')
        except KeyError:
            raise BadRequest('missing boundary')

        header = None
        body = bytearray()

        header_size = 0
        body_size = 0
        content_length = 0
        paused = False

        if self._read_instance is None:
            self._read_instance = self.stream()

        while limit > 0 and self._read_buf != b'--%s--\r\n' % boundary:
            data = b''

            if not paused:
                try:
                    data = await self._read_instance.__anext__()
                except StopAsyncIteration:
                    if header_size == -1 or body_size == -1:
                        del body[:]
                        raise BadRequest(
                            'malformed multipart/form-data: incomplete read'
                        )

            if header is None:
                self._read_buf.extend(data)
                header_size = self._read_buf.find(b'\r\n\r\n')

                if header_size == -1:
                    if len(self._read_buf) > 8192:
                        raise BadRequest(
                            'malformed multipart/form-data: header too large'
                        )

                    paused = False
                else:
                    body.extend(self._read_buf[header_size + 4:])
                    info = {}

                    if header_size <= 8192 and self._read_buf.startswith(
                            b'--%s\r\n' % boundary):
                        header = self.header.parse(
                            self._read_buf,
                            header_size=header_size
                        ).headers

                        if b'content-disposition' in header:
                            for k, v in parse_qsl(
                                    header[b'content-disposition']
                                    .replace(b'; ', b'&').replace(b';', b'&')
                                    .decode('latin-1'), max_num_fields=100):
                                info[k] = v.strip('"')

                        if b'content-length' in header:
                            content_length = int(header[b'content-length'])
                            info['length'] = content_length

                        if b'content-type' in header:
                            info['type'] = header[b'content-type'].decode('latin-1')  # noqa: E501
                    else:
                        header = {}

                continue

            body.extend(data)
            body_size = body.find(b'\r\n--%s' % boundary, content_length)

            if body_size == -1:
                paused = False
                continue

            yield info, body[:body_size]

            self._read_buf[:] = body[body_size + 2:]
            header = None
            content_length = 0
            paused = True
            limit -= 1

            del body[:]
