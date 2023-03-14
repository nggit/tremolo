# Copyright (c) 2023 nggit

from urllib.parse import parse_qs

from .request import Request

class HTTPRequest(Request):
    def __init__(self, protocol, header):
        super().__init__(protocol)

        self.is_valid = header.is_valid_request
        self.headers = header.getheaders()
        self.host = header.gethost()

        if isinstance(self.host, list):
            self.host = self.host[0]

        self.method = header.getmethod().upper()
        self.path = header.getpath()
        self.version = header.getversion()

        if self.version != b'1.0':
            self.version = b'1.1'

        self._content_length = -1
        self._content_type = b'application/octet-stream'
        self._body = bytearray()
        self._http_continue = False
        self._http_keepalive = False
        self._http_upgrade = False
        self._params = {}

    def append_body(self, value):
        self._body.extend(value)

    def clear_body(self):
        del self._body[:]
        super().clear_body()

    async def recv_timeout(self, timeout):
        if self.protocol.queue[1] is not None:
            self.protocol.queue[1].put_nowait(
                b'HTTP/%s 408 Request Timeout\r\nConnection: close\r\n\r\n' % self.version
            )

            self._http_keepalive = False
            self.protocol.queue[1].put_nowait(None)

        await super().recv_timeout(timeout)

    async def body(self, cache=True):
        if self._body == b'' or not cache:
            async for data in self.read(cache=False):
                self.append_body(data)

        return self._body

    async def read(self, cache=True):
        if cache and self._body != b'':
            yield self._body
            return

        if b'transfer-encoding' in self.headers and self.headers[b'transfer-encoding'].lower().find(b'chunked') > -1:
            buf = bytearray()
            agen = self.recv()
            paused = False
            tobe_read = 0

            while buf != b'0\r\n\r\n':
                if not paused:
                    try:
                        data = await agen.__anext__()

                        buf.extend(data)
                    except StopAsyncIteration:
                        if not buf.endswith(b'0\r\n\r\n'):
                            return

                    if buf == b'':
                        return

                if tobe_read > 0:
                    data = buf[:tobe_read]

                    yield data
                    del buf[:tobe_read]

                    tobe_read -= len(data)

                    if tobe_read <= 0:
                        del buf[:2]

                    continue

                i = buf.find(b'\r\n')

                if i > -1:
                    paused = True
                else:
                    paused = False

                    continue

                try:
                    chunk_size = int(buf[:i].split(b';')[0], 16)
                except ValueError:
                    if self.protocol.queue[1] is not None:
                        self.protocol.queue[1].put_nowait(
                            b'HTTP/%s 400 Bad Request\r\nConnection: close\r\n\r\n' % self.version
                        )

                        self._http_keepalive = False
                        self.protocol.queue[1].put_nowait(None)

                    del buf[:]
                    self.protocol.options['logger'].error('bad chunked encoding')
                    return

                data = buf[i + 2:i + 2 + chunk_size]
                tobe_read = chunk_size - len(data)

                yield data

                if tobe_read > 0:
                    paused = False

                    del buf[:i + 2 + chunk_size]
                else:
                    del buf[:chunk_size + i + 4]
        else:
            async for data in self.recv():
                yield data

    @property
    def content_length(self):
        return self._content_length

    @content_length.setter
    def content_length(self, value):
        self._content_length = value

    @property
    def content_type(self):
        return self._content_type

    @content_type.setter
    def content_type(self, value):
        self._content_type = value

    @property
    def http_continue(self):
        return self._http_continue

    @http_continue.setter
    def http_continue(self, value):
        self._http_continue = value

    @property
    def http_keepalive(self):
        return self._http_keepalive

    @http_keepalive.setter
    def http_keepalive(self, value):
        self._http_keepalive = value

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
                        b'; '.join(self.headers[b'cookie']).replace(b'; ', b'&').replace(b';', b'&').decode(encoding='latin-1')
                    )
                else:
                    self._params['cookies'] = parse_qs(
                        self.headers[b'cookie'].replace(b'; ', b'&').replace(b';', b'&').decode(encoding='latin-1')
                    )

            return self._params['cookies']

    @property
    async def form(self):
        try:
            return self._params['post']
        except KeyError:
            self._params['post'] = {}

            if self._content_type.find(b'application/x-www-form-urlencoded') > -1:
                async for data in self.read():
                    self.append_body(data)

                    if self.body_size > 8 * 1048576:
                        break

                if 2 < self.body_size <= 8 * 1048576:
                    self._params['post'] = parse_qs(self._body.decode(encoding='latin-1'))

            return self._params['post']

    @property
    def query(self):
        return self._params['query']

    @query.setter
    def query(self, value):
        self._params['query'] = value
