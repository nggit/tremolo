# Copyright (c) 2023 nggit

import asyncio
import traceback

from .parsed import ParseHeader
from .http_request import HTTPRequest
from .http_response import HTTPResponse

try:
    from asyncio import InvalidStateError
except ImportError:
    from asyncio.base_futures import InvalidStateError

class TremoloProtocol(asyncio.Protocol):
    def __init__(self, *args, **kwargs):
        self._options = kwargs
        self._transport = None
        self._queue = {0: None, 1: None}

        if 'loop' in kwargs:
            self._loop = kwargs['loop']
        else:
            self._loop = asyncio.get_event_loop()

    @property
    def loop(self):
        return self._loop

    @property
    def options(self):
        return self._options

    @property
    def transport(self):
        return self._transport

    @property
    def queue(self):
        return self._queue

    def connection_made(self, transport):
        self._transport = transport
        self._queue = {
            0: asyncio.Queue(),
            1: asyncio.Queue()
        }
        self._request = None
        self._response = None
        self._tasks = []

        self._data = bytearray()
        self._body_size = 0
        self._cancel_timeouts = dict(receive=self._loop.create_future())

        for task in (self._transfer_data(), self.set_timeout(self._cancel_timeouts['receive'],
                                                             timeout_cb=self.receive_timeout)):
            self._tasks.append(self._loop.create_task(task))

    async def receive_timeout(self, timeout):
        self._options['logger'].info('request timeout after {:d}s'.format(timeout))

    async def keepalive_timeout(self, timeout):
        self._options['logger'].info('keepalive timeout after {:d}s'.format(timeout))

    async def set_timeout(self, cancel_timeout, timeout=30, timeout_cb=None):
        _, pending = await asyncio.wait([cancel_timeout], timeout=timeout)

        if pending:
            for task in pending:
                task.cancel()

            if self._transport is not None:
                if callable(timeout_cb):
                    await timeout_cb(timeout)

                if self._transport is not None and self._transport.is_closing() is False:
                    self._transport.abort()

    async def _put_to_queue(self, data, queue=None, transport=None, rate=1048576, buffer_size=16 * 1024):
        data_size = len(data)

        if (data_size >= 2 * buffer_size):
            mv = memoryview(data)

            while mv and queue is not None:
                queue.put_nowait(mv[:buffer_size].tobytes())
                await asyncio.sleep(1 / (rate / max(queue.qsize(), 1) / mv[:buffer_size].nbytes))
                mv = mv[buffer_size:]

        elif data != b'' and queue is not None:
            queue.put_nowait(data)
            await asyncio.sleep(1 / (rate / max(queue.qsize(), 1) / data_size))

        if transport is not None:
            self._body_size += data_size

            if self._request is not None and self._body_size >= self._request.content_length and queue is not None:
                queue.put_nowait(None)
            elif self._body_size < self._options['client_max_body_size']:
                transport.resume_reading()
            else:
                transport.write(b'HTTP/%s 413 Payload Too Large\r\nConnection: close\r\n\r\n' % self._request.version)

                if self._queue[1] is not None:
                    if self._request is not None:
                        self._request.http_keepalive = False

                    self._queue[1].put_nowait(None)

    async def body_received(self, request, response):
        return

    async def header_received(self, request, response):
        return

    async def handle_exception(self, exc, request, response):
        request.http_keepalive = False

        if self.options['debug']:
            data = b'<ul><li>%s</li></ul>' % '</li><li>'.join(
                traceback.TracebackException.from_exception(exc).format()
            ).encode(encoding='latin-1')
        else:
            data = b'Internal server error.'

        await response.write(
            b'HTTP/%s 500 Internal Server Error\r\nContent-Type: text/html\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s' % (
            request.version, len(data), data))

        await response.write(None)
        self._options['logger'].error(': '.join(
            (request.path.decode(encoding='latin-1'), exc.__class__.__name__, str(exc))
        ), exc_info={True: exc, False: False}[self._options['debug']])

    async def _handle_request_header(self, data, sep):
        self._data = None

        header = ParseHeader(data, excludes=[b'proxy'])

        if header.is_request:
            self._request = HTTPRequest(self, header)
            self._response = HTTPResponse(self, self._request)

            try:
                if b'connection' in self._request.headers:
                    if self._request.headers[b'connection'].find(b'close') == -1:
                        self._request.http_keepalive = True
                elif self._request.version == b'1.1':
                    self._request.http_keepalive = True

                if self._request.method in (b'POST', b'PUT', b'PATCH'):
                    if b'content-type' in self._request.headers:
                        self._request.content_type = self._request.headers[b'content-type']

                    if b'content-length' in self._request.headers:
                        self._request.content_length = int(self._request.headers[b'content-length'])

                    if b'expect' in self._request.headers and self._request.headers[b'expect'] == b'100-continue':
                        if self._request.content_length > self._options['client_max_body_size']:
                            if self._queue[1] is not None:
                                self._queue[1].put_nowait(
                                    b'HTTP/%s 417 Expectation Failed\r\nConnection: close\r\n\r\n' % self._request.version
                                )
                                self._request.http_keepalive = False
                                self._queue[1].put_nowait(None)

                            return
                        elif self._queue[1] is not None:
                            self._queue[1].put_nowait(b'HTTP/%s 100 Continue\r\n\r\n' % self._request.version)
                    elif self._request.content_length > self._options['client_max_body_size']:
                        if self._queue[1] is not None:
                            self._queue[1].put_nowait(
                                b'HTTP/%s 413 Payload Too Large\r\nConnection: close\r\n\r\n' % self._request.version
                            )
                            self._request.http_keepalive = False
                            self._queue[1].put_nowait(None)

                        return

                    await self._put_to_queue(
                        data[sep + 4:], queue=self._queue[0], transport=self._transport, rate=self._options['upload_rate']
                    )
                    await self.body_received(self._request, self._response)

                await self.header_received(self._request, self._response)
            except Exception as exc:
                await self.handle_exception(exc, self._request, self._response)
        else:
            if self._queue[1] is not None:
                self._queue[1].put_nowait(None)

    def data_received(self, data):
        if self._data is not None:
            self._data.extend(data)
            sep = self._data.find(b'\r\n\r\n')

            if sep > -1 and sep < 8192:
                self._transport.pause_reading()

                for i in self._cancel_timeouts:
                    if self._cancel_timeouts[i].done() is False:
                        self._cancel_timeouts[i].set_result(None)

                self._tasks.append(self._loop.create_task(self._handle_request_header(self._data, sep)))
            elif sep > 8192:
                self._options['logger'].info('request header too large')
                self._transport.abort()
            elif not (sep == -1 and len(self._data) < 8192):
                self._options['logger'].info('bad request')
                self._transport.abort()

            return

        self._transport.pause_reading()
        self._loop.create_task(
            self._put_to_queue(data, queue=self._queue[0], transport=self._transport, rate=self._options['upload_rate'])
        )

    def eof_received(self):
        self._queue[0].put_nowait(None)

    async def _transfer_data(self):
        while True:
            data = await self._queue[1].get()
            self._queue[1].task_done()

            try:
                if data is None:
                    if self._request is not None and self._request.http_keepalive and self._data is None:
                        for i, task in enumerate(self._tasks):
                            try:
                                exc = task.exception()

                                if exc:
                                    self._options['logger'].error(': '.join(
                                        (exc.__class__.__name__, str(exc))
                                    ), exc_info={True: exc, False: False}[self._options['debug']])

                                del self._tasks[i]
                            except InvalidStateError:
                                pass

                        self._data = bytearray()
                        self._body_size = 0
                        self._cancel_timeouts['keepalive'] = self._loop.create_future()

                        self._tasks.append(self._loop.create_task(self.set_timeout(self._cancel_timeouts['keepalive'],
                                                                                   timeout_cb=self.keepalive_timeout)))
                        self._transport.resume_reading()
                        continue
                    else:
                        if self._transport.can_write_eof():
                            self._transport.write_eof()

                        self._transport.close()
                        return

                self._transport.write(data)
            except Exception as exc:
                if self._transport is not None:
                    self._transport.abort()

                raise exc

    def connection_lost(self, exc):
        for task in self._tasks:
            try:
                exc = task.exception()

                if exc:
                    self._options['logger'].error(': '.join(
                        (exc.__class__.__name__, str(exc))
                    ), exc_info={True: exc, False: False}[self._options['debug']])
            except InvalidStateError:
                task.cancel()

        self._transport = None
        self._queue = {0: None, 1: None}
        self._request = None
        self._response = None
        self._data = None
