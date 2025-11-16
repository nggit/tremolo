# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Anggit Arfanto

import json

from .http_header import HTTPHeader


class ChunkedDecoder:
    def __init__(self):
        self._chunk_size = -1
        self._bytes_unread = 0

    def parse(self, buf, chunk_max_size=16384):
        while True:
            if self._bytes_unread > 2:
                if len(buf) < min(self._bytes_unread - 2, chunk_max_size):
                    return

                data = bytes(buf[:self._bytes_unread - 2])
                del buf[:self._bytes_unread - 2]

                self._bytes_unread -= len(data)
                yield data
                continue

            if self._bytes_unread == 2:
                if len(buf) < 2:
                    return

                if not buf.startswith(b'\r\n'):
                    raise ValueError('bad chunked encoding: '
                                     'invalid chunk terminator')

                if self._chunk_size == 0:
                    del buf[:]
                    yield None

            i = buf.find(b'\r\n', self._bytes_unread)

            if i == -1:
                if len(buf) > 64:
                    raise ValueError('bad chunked encoding: no chunk size')

                return

            self._chunk_size = int(
                buf[self._bytes_unread:i].split(b';', 1)[0], 16
            )

            data = bytes(buf[i + 2:i + 2 + self._chunk_size])
            del buf[:i + 2 + self._chunk_size]

            self._bytes_unread = self._chunk_size - len(data) + 2
            yield data


class JSONResponse(dict):
    def __init__(self, response, max_size, **kwargs):
        self._response = response
        self._body = response.body(max_size=max_size)
        self._kwargs = kwargs

        if response.client.sock.getblocking():
            try:
                self.update(json.loads(self._body.decode(), **kwargs))
            finally:
                del self._body[:]

    def __await__(self):
        async def body():
            self.update(
                json.loads((await self._body).decode(), **self._kwargs)
            )
            return self

        return body().__await__()


class HTTPResponse:
    def __init__(self, client, *args, defer=False):
        self.client = client
        self.request = args
        self.defer = defer
        self.header = None
        self.status = 0
        self.message = b''
        self.url = b''
        self.content_length = -2  # unknown length

        self._buf = bytearray()
        self._chunked = ChunkedDecoder()

        if client.sock.getblocking():
            for retries in range(client.retries, -1, -1):
                try:
                    if retries != client.retries:
                        client.sock.close()
                        client.__enter__()

                    if args:
                        client.sock.sendall(b'%s\r\n%s\r\n\r\n%s' % args)

                    while self.header is None and not defer:
                        self.__next__()

                    break
                except OSError:
                    if retries == 0:
                        raise
                except StopIteration:
                    if retries == client.retries:
                        break

    @property
    def headers(self):
        return self.header.headers

    def body(self, max_size=100 * 1048576):
        if self.content_length > max_size:
            raise ValueError(f'response body too large: {self.content_length}')

        body = bytearray()

        if self.client.sock.getblocking():
            for data in self:
                body.extend(data)

                if len(body) > max_size:
                    raise ValueError('response body too large')

            return body

        async def coro():
            async for data in self:
                body.extend(data)

                if len(body) > max_size:
                    raise ValueError('response body too large')

            return body

        return coro()

    def json(self, max_size=1048576, **kwargs):
        return JSONResponse(self, max_size, **kwargs)

    def __await__(self):
        async def header():
            for retries in range(self.client.retries, -1, -1):
                try:
                    if retries != self.client.retries:
                        self.client.sock.close()
                        await self.client.__aenter__()

                    if self.request:
                        await self.client.loop.sock_sendall(
                            self.client.sock,
                            b'%s\r\n%s\r\n\r\n%s' % self.request
                        )

                    while self.header is None and not self.defer:
                        await self.__anext__()

                    break
                except OSError:
                    if retries == 0:
                        raise
                except StopAsyncIteration:
                    if retries == self.client.retries:
                        break

            return self

        return header().__await__()

    def __iter__(self):
        return self

    def _handle_response(self, data):
        self._buf.extend(data)
        header_size = self._buf.find(b'\r\n\r\n') + 2

        if header_size == 1:
            if len(self._buf) > 65536:
                raise ValueError('response header too large')

            return

        # -- HEADER --
        self.header = HTTPHeader().parse(self._buf, header_size)
        self.status = self.header.status
        self.message = self.header.message

        del self._buf[:header_size + 2]

        if b'chunked' in self.header.headers.getlist(b'transfer-encoding'):
            self.content_length = -1
        elif b'content-length' in self.header.headers:
            self.content_length = int(
                self.header.headers[b'content-length'][0]
            )

        if 300 <= self.status < 400 and b'location' in self.header.headers:
            self.url = self.header.headers[b'location'][0]

        if b'set-cookie' in self.header.headers:
            for cookie in self.header.headers[b'set-cookie']:
                if cookie:
                    self.client.update_cookie(cookie.split(b';', 1)[0])

    def __next__(self):
        if self.header is None:
            data = self.client.sock.recv(8192)

            if data == b'':
                raise StopIteration

            self._handle_response(data)
            return b''

        if self.status == 100:
            self.header = None
            raise StopIteration

        # --- BODY ---
        if self.content_length == -1:  # chunked
            while True:
                if self._buf:
                    for data in self._chunked.parse(self._buf):
                        if data is None:
                            self.content_length = 0
                            raise StopIteration

                        return data

                data = self.client.sock.recv(16384)

                if data == b'':
                    raise StopIteration

                self._buf.extend(data)

        # Content-Length
        if self.content_length == 0:
            raise StopIteration

        bufsize = 16384 if self.content_length <= -2 else self.content_length

        if self._buf:
            data = bytes(self._buf)
            del self._buf[:]
        else:
            data = self.client.sock.recv(bufsize)

        if data == b'':
            raise StopIteration

        self.content_length -= len(data)
        return data

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.header is None:
            data = await self.client.loop.sock_recv(self.client.sock, 8192)

            if data == b'':
                raise StopAsyncIteration

            self._handle_response(data)
            return b''

        if self.status == 100:
            self.header = None
            raise StopAsyncIteration

        # --- BODY ---
        if self.content_length == -1:  # chunked
            while True:
                if self._buf:
                    for data in self._chunked.parse(self._buf):
                        if data is None:
                            self.content_length = 0
                            raise StopAsyncIteration

                        return data

                data = await self.client.loop.sock_recv(self.client.sock,
                                                        16384)

                if data == b'':
                    raise StopAsyncIteration

                self._buf.extend(data)

        # Content-Length
        if self.content_length == 0:
            raise StopAsyncIteration

        bufsize = 16384 if self.content_length <= -2 else self.content_length

        if self._buf:
            data = bytes(self._buf)
            del self._buf[:]
        else:
            data = await self.client.loop.sock_recv(self.client.sock, bufsize)

        if data == b'':
            raise StopAsyncIteration

        self.content_length -= len(data)
        return data
