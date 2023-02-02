# Copyright (c) 2023 nggit

from .request import Request

class HTTPRequest(Request):
    def __init__(self, protocol, header):
        super().__init__(protocol)

        self._protocol = protocol
        self._header = header
        self.is_valid = header.is_valid_request
        self.headers = header.getheaders()
        self.host = header.gethost()
        self.method = header.getmethod()
        self.path = header.getpath()
        self.version = header.getversion()

        self._content_length = -1
        self._content_type = b'application/octet-stream'
        self._body = bytearray()
        self._cookies = {}
        self._http_keepalive = False
        self._params = {}
        self._query = {}

    async def read_timeout(self, timeout):
        if self._protocol.queue[1] is not None:
            self._protocol.queue[1].put_nowait(b'HTTP/%s 408 Request Timeout\r\nConnection: close\r\n\r\n' % self.version)

            self._http_keepalive = False
            self._protocol.queue[1].put_nowait(None)

        del self._body[:]

    async def body(self):
        if self._body == bytearray():
            async for data in self.read():
                self._body.extend(data)

        return self._body

    async def read(self):
        if b'transfer-encoding' in self.headers and self.headers[b'transfer-encoding'].find(b'chunked') > -1:
            buf = bytearray()
            agen = super().read()

            while buf != b'0\r\n\r\n':
                try:
                    buf.extend(await agen.__anext__())
                except StopAsyncIteration:
                    if buf == b'':
                        raise

                i = buf.find(b'\r\n')

                if i > -1:
                    chunk_size = int(buf[:i], 16)

                    yield buf[i + 2:i + 2 + chunk_size]
                    del buf[:chunk_size + i + 4]
        else:
            async for data in super().read():
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
    def cookies(self):
        return self._cookies

    @cookies.setter
    def cookies(self, value):
        self._cookies = value

    @property
    def http_keepalive(self):
        return self._http_keepalive

    @http_keepalive.setter
    def http_keepalive(self, value):
        self._http_keepalive = value

    @property
    def params(self):
        return self._params

    @params.setter
    def params(self, value):
        self._params = value

    @property
    def query(self):
        return self._query

    @query.setter
    def query(self, value):
        self._query = value
