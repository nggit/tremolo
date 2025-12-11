# SPDX-License-Identifier: MIT
# Copyright (c) 2023 Anggit Arfanto

import os
import time

from urllib.parse import parse_qs

from tremolo.utils import parse_fields, parse_int
from .http_exceptions import BadRequest, PayloadTooLarge
from .http_response import HTTPResponse
from .request import Request


class MultipartFile(dict):
    def __init__(self, files):
        self.files = files

    async def stream(self):
        if 'data' in self:
            yield self.pop('data')

            while not self['eof']:
                yield (await self.files.__anext__()).pop('data')


class HTTPRequest(Request):
    __slots__ = ('_ip', '_scheme', 'header', 'headers', 'is_valid',
                 'host', 'method', 'url', 'path', 'query_string', 'version',
                 'content_length', 'http_continue', 'http_keepalive',
                 'has_body', '_body', '_read_buf', '_stream', '_files')

    def __init__(self, protocol, header):
        super().__init__(protocol)

        self._ip = None
        self._scheme = None
        self.header = header
        self.headers = header.headers
        self.is_valid = header.is_valid
        self.host = header.gethost()
        self.method = header.method
        self.url = header.url
        self.path, _, self.query_string = self.url.partition(b'?')
        self.version = header.version

        self.content_length = -1
        self.http_continue = False
        self.http_keepalive = False
        self.has_body = False

        self._body = bytearray()
        self._read_buf = bytearray()
        self._stream = None
        self._files = None

    @property
    def ip(self):
        if not self._ip:
            values = self.headers.get(b'x-forwarded-for')
            ip = values[0].strip() if values else b''

            if ip == b'' and self.client is not None:
                self._ip = self.client[0].encode('utf-8')
            else:
                self._ip = ip.split(b',', 1)[0]

        return self._ip

    @property
    def scheme(self):
        if not self._scheme:
            values = self.headers.get(b'x-forwarded-proto')
            scheme = values[0].strip() if values else b''

            if scheme == b'' and self.is_secure:
                self._scheme = b'https'
            else:
                self._scheme = scheme or b'http'

        return self._scheme

    @property
    def content_type(self):
        # don't lower() content-type, as it may contain a boundary
        if b'content-type' in self.headers:
            return self.headers[b'content-type'][0]

        return b'application/octet-stream'

    @property
    def transfer_encoding(self):
        return self.headers.getlist(b'transfer-encoding')

    @property
    def upgraded(self):
        return self._body is None

    @upgraded.setter
    def upgraded(self, value):
        self._body = None
        del self._read_buf[:]

    def uid(self, length=32, *, ts_offset=0):
        if self.client is None:
            port = self.socket.fileno()
        else:
            port = self.client[1]  # 0 - 65535

        prefix = (
            int(time.time() + ts_offset).to_bytes(4, byteorder='big') +
            int.to_bytes((port << 16) | (os.getpid() & 0xffff),
                         4, byteorder='big')
        )[:length]  # 8 Bytes

        return prefix + os.urandom(length - len(prefix))

    def create_response(self):
        return HTTPResponse(self)

    def clear(self):
        self.headers.clear()

        if self._body:
            del self._body[:]

        del self._read_buf[:]

        super().clear()

    async def handler_exit(self):
        if self._files is not None:
            await self._files.aclose()

        if self._stream is not None:
            await self._stream.aclose()

    async def body(self, **kwargs):
        async for data in self.stream(**kwargs):
            self._body.extend(data)

        return self._body

    async def read(self, size=-1, *, timeout=None):
        return await self.recv(size, timeout=timeout, raw=False)

    def eof(self):
        return self.content_length == 0 and self._read_buf == b''

    async def recv(self, size=-1, *, timeout=None, raw=True):
        if size == 0 or self.eof():
            return b''

        if self._stream is None:
            self._stream = self.stream(timeout, raw)
        elif timeout is not None:  # update
            self.timeout = timeout

        if size == -1:
            return await self._stream.__anext__()

        try:
            while len(self._read_buf) < size:
                self._read_buf.extend(await self._stream.__anext__())

            return bytes(self._read_buf[:size])
        except StopAsyncIteration:
            return bytes(self._read_buf)
        finally:
            del self._read_buf[:size]

    async def stream(self, timeout=None, raw=False):
        if self.content_length == 0:
            return

        if self.http_continue:
            self.server.send_continue()

        if raw or self.content_length != -1:
            if (self.content_length >
                    self.server.options['client_max_body_size']):
                raise PayloadTooLarge

            async for data in super().recv(timeout):
                yield bytes(data)
        elif b'chunked' in self.transfer_encoding:
            buf = bytearray()
            agen = super().recv(timeout)
            paused = False
            bytes_unread = 0
            chunk_size = -1

            while True:
                if not paused:
                    buf.extend(await agen.__anext__())

                if bytes_unread > 2:
                    data = bytes(buf[:bytes_unread - 2])
                    del buf[:bytes_unread - 2]

                    if data:
                        yield data
                        bytes_unread -= len(data)

                    paused = False
                    continue

                if bytes_unread == 2:
                    if len(buf) < 2:
                        paused = False
                        continue

                    if not buf.startswith(b'\r\n'):
                        raise BadRequest('bad chunked encoding: '
                                         'invalid chunk terminator')

                    if chunk_size == 0:
                        if self.server.options['experimental']:
                            self.server.queue[0].queue.appendleft(buf[2:])
                        else:
                            self.http_keepalive = False

                        del buf[:]
                        break

                # bytes_unread should only be either 0 or 2 at this point
                i = buf.find(b'\r\n', bytes_unread)

                if i == -1:
                    if len(buf) > 64:
                        raise BadRequest('bad chunked encoding: no chunk size')

                    paused = False
                    continue

                try:
                    chunk_size = parse_int(
                        buf[bytes_unread:i].split(b';', 1)[0], 16
                    )
                except ValueError as exc:
                    raise BadRequest('bad chunked encoding') from exc

                data = bytes(buf[i + 2:i + 2 + chunk_size])
                del buf[:i + 2 + chunk_size]

                if data:
                    yield data

                bytes_unread = chunk_size - len(data) + 2
                paused = True

        self.content_length = 0

        if self._stream is not None:  # extra for recv(size=-1)
            yield b''

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
                cookie = b';'.join(self.headers[b'cookie'])

                for k, v in parse_fields(cookie):
                    k = k.decode('latin-1')

                    if k in self.params['cookies']:
                        self.params['cookies'][k].append(v.decode('latin-1'))
                    else:
                        self.params['cookies'][k] = [v.decode('latin-1')]

            return self.params['cookies']

    async def form(self, max_fields=100, *, max_size=8 * 1048576):
        try:
            return self.params['post']
        except KeyError:
            content_type = self.headers.getlist(b'content-type', b';')
            self.params['post'] = {}
            self.params['files'] = {}

            if b'application/x-www-form-urlencoded' in content_type:
                async for data in self.stream():
                    self._body.extend(data)

                    if self.body_size > max_size:
                        raise ValueError('form size limit reached') from None

                if 2 < self.body_size <= max_size:
                    self.params['post'] = parse_qs(
                        self._body.decode('latin-1'),
                        max_num_fields=max_fields
                    )

                return self.params['post']

            if b'multipart/form-data' in content_type:
                self._files = self.files(max_fields, max_file_size=max_size)

                async for part in self._files:
                    if not part.pop('eof'):
                        raise ValueError(
                            'fragmented file. consider increasing the '
                            'max_size limit or stream using request.files()'
                        ) from None

                    name = part.pop('name', '')

                    if 'filename' in part:
                        if part['filename'] == '':
                            continue

                        if name in self.params['files']:
                            self.params['files'][name].append(part)
                        else:
                            self.params['files'][name] = [part]
                    else:
                        if name in self.params['post']:
                            self.params['post'][name].append(
                                part['data'].decode()
                            )
                        else:
                            self.params['post'][name] = [part['data'].decode()]

                return self.params['post']

            raise BadRequest('invalid Content-Type') from None

    async def files(self, max_files=1024, *, max_file_size=100 * 1048576):
        if self.eof():
            return

        if self._files is None:
            self._files = self.files(max_files, max_file_size=max_file_size)

            async for part in self._files:
                yield part

            return

        for key, boundary in parse_fields(self.content_type):
            if key == b'boundary' and boundary:
                break
        else:
            raise BadRequest('missing boundary')

        boundary_size = len(boundary)
        body = bytearray()

        header_size = 0
        body_size = 0
        paused = False
        part = None  # represents a field/file received in a multipart request

        while max_files > 0:
            data = b''

            if not paused:
                data = await self.read()

                if not data:
                    if self._read_buf.startswith(b'--%s--' % boundary):
                        del self._read_buf[:]  # set eof()
                        return

                    if header_size == 1 or body_size == -1:
                        raise BadRequest(
                            'malformed multipart/form-data: incomplete read'
                        )

            if part is None:
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
                    part = MultipartFile(self._files)

                    # use find() instead of startswith() to ignore the preamble
                    if self._read_buf.find(b'--%s\r\n' % boundary,
                                           0, header_size) != -1:
                        header = self.header.parse(self._read_buf,
                                                   header_size).headers

                        if b'content-disposition' in header:
                            for k, v in parse_fields(
                                    header[b'content-disposition'][0]):
                                part[k.decode('latin-1')] = v.decode('latin-1')

                        if b'content-type' in header:
                            part['type'] = header[b'content-type'][
                                                  0].decode('latin-1')
                continue

            body.extend(data)
            body_size = body.find(b'\r\n--%s' % boundary)

            if body_size == -1:
                if len(body) >= max_file_size > boundary_size + 4:
                    part['data'] = bytes(body[:-boundary_size - 4])
                    part['eof'] = False
                    yield part

                    del body[:-boundary_size - 4]

                paused = False
                continue

            part['data'] = bytes(body[:body_size])
            part['eof'] = True
            yield part

            self._read_buf[:] = body[body_size + 2:]
            paused = True
            part = None
            max_files -= 1

            del body[:]
