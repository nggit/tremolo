# Copyright (c) 2023 nggit

from urllib.parse import parse_qs, parse_qsl

from .http_exception import BadRequest, PayloadTooLarge, RequestTimeout
from .request import Request


class HTTPRequest(Request):
    def __init__(self, protocol, header):
        super().__init__(protocol)

        self.client = protocol.transport.get_extra_info('peername')
        self._ip = None
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
        self._http_upgrade = False
        self._params = {}

    @property
    def ip(self):
        if self._ip:
            return self._ip

        ip = self.headers.get(b'x-forwarded-for', b'')

        if isinstance(ip, list):
            ip = ip[0]

        ip = ip.strip()

        if ip == b'' and isinstance(self.client, tuple):
            self._ip = self.client[0].encode('utf-8')
        else:
            self._ip = ip[:(ip + b',').find(b',')]

        return self._ip

    def append_body(self, value):
        self._body.extend(value)

    def clear_body(self):
        del self._body[:]
        super().clear_body()

    async def recv_timeout(self, timeout):
        raise RequestTimeout

    async def body(self, cache=True):
        if self._body == b'' or not cache:
            async for data in self.read(cache=False):
                self.append_body(data)

        return self._body

    async def read(self, cache=True):
        if cache and self._body != b'':
            yield self._body

            if not self.body_size < self.content_length:
                return

        if (self.content_length >
                self.protocol.options['client_max_body_size']):
            raise PayloadTooLarge

        if b'chunked' in self.transfer_encoding:
            buf = bytearray()
            agen = self.recv()
            paused = False
            tobe_read = 0

            while buf != b'0\r\n\r\n':
                if not paused:
                    try:
                        buf.extend(await agen.__anext__())
                    except StopAsyncIteration:
                        if not buf.endswith(b'0\r\n\r\n'):
                            del buf[:]
                            raise BadRequest(
                                'bad chunked encoding: incomplete read'
                            )

                if tobe_read > 0:
                    data = buf[:tobe_read]

                    yield data
                    del buf[:tobe_read]

                    tobe_read -= len(data)

                    if tobe_read > 0:
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
                    tobe_read = chunk_size - len(data)

                    yield data

                    if tobe_read > 0:
                        paused = False
                        del buf[:]
                    else:
                        paused = True
                        del buf[:chunk_size + i + 4]
        else:
            async for data in self.recv():
                yield data

    @property
    def http_upgrade(self):
        return self._http_upgrade

    @http_upgrade.setter
    def http_upgrade(self, value):
        self.clear_body()
        self._http_upgrade = value

    @property
    def params(self):
        return self._params

    @property
    def cookies(self):
        try:
            return self._params['cookies']
        except KeyError:
            self._params['cookies'] = {}

            if b'cookie' in self.headers:
                if isinstance(self.headers[b'cookie'], list):
                    self._params['cookies'] = parse_qs(
                        b'; '.join(self.headers[b'cookie'])
                        .replace(b'; ', b'&').replace(b';', b'&')
                        .decode('latin-1')
                    )
                else:
                    self._params['cookies'] = parse_qs(
                        self.headers[b'cookie'].replace(b'; ', b'&')
                        .replace(b';', b'&').decode('latin-1')
                    )

            return self._params['cookies']

    async def form(self, limit=8 * 1048576):
        try:
            return self._params['post']
        except KeyError:
            self._params['post'] = {}

            if (b'application/x-www-form-urlencoded' in
                    self.content_type.lower()):
                async for data in self.read():
                    self.append_body(data)

                    if self.body_size > limit:
                        break

                if 2 < self.body_size <= limit:
                    self._params['post'] = parse_qs(
                        self._body.decode('latin-1')
                    )

            return self._params['post']

    async def files(self):
        ct = parse_qs(
            self.content_type.replace(b'; ', b'&').replace(b';', b'&')
            .decode('latin-1')
        )

        try:
            boundary = ct['boundary'][-1].encode('latin-1')
        except KeyError:
            raise BadRequest('missing boundary')

        header = bytearray()
        body = bytearray()

        header_size = 0
        body_size = 0
        content_length = 0

        agen = self.read()
        paused = False

        while header != b'--%s--\r\n' % boundary:
            data = b''

            if not paused:
                try:
                    data = await agen.__anext__()
                except StopAsyncIteration:
                    if header_size == -1 or body_size == -1:
                        del body[:]
                        raise BadRequest('malformed multipart/form-data')

            if isinstance(header, bytearray):
                header.extend(data)
                header_size = header.find(b'\r\n\r\n')

                if header_size == -1:
                    if len(header) > 8192:
                        del header[:]
                        raise BadRequest('malformed multipart/form-data')

                    paused = False
                else:
                    body = header[header_size + 4:]
                    info = {}

                    if header_size <= 8192 and header.startswith(
                            b'--%s\r\n' % boundary):
                        header = self.header.parse(
                            header,
                            header_size=header_size
                        ).headers

                        if b'content-disposition' in header:
                            for k, v in parse_qsl(
                                    header[b'content-disposition']
                                    .replace(b'; ', b'&').replace(b';', b'&')
                                    .decode('latin-1')):
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

            header = body[body_size + 2:]
            content_length = 0
            paused = True

            del body[:]

    @property
    def query(self):
        return self._params['query']

    @query.setter
    def query(self, value):
        self._params['query'] = value
