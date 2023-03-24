# Copyright (c) 2023 nggit

import asyncio
import traceback

from .http_request import HTTPRequest
from .http_response import HTTPResponse

class HTTPProtocol(asyncio.Protocol):
    def __init__(self, context, **kwargs):
        assert context.tasks == []

        self._context = context
        self._options = kwargs

        try:
            self._loop = kwargs['loop']
        except KeyError:
            self._loop = asyncio.get_event_loop()

        self._transport = None
        self._queue = (None, None)
        self._header = None

    @property
    def context(self):
        return self._context

    @property
    def tasks(self):
        return self._context.tasks

    @property
    def options(self):
        return self._options

    @property
    def loop(self):
        return self._loop

    @property
    def transport(self):
        return self._transport

    @property
    def queue(self):
        return self._queue

    @property
    def header(self):
        return self._header

    def connection_made(self, transport):
        self._transport = transport
        self._conn = self._options['_pool'].get()
        self._queue = self._conn['queue']
        self._header = self._conn['header']
        self._request = None
        self._response = None

        self._data = bytearray()
        self._timeout_waiters = {'request': self._loop.create_future()}

        for task in (self._send_data(), self.set_timeout(self._timeout_waiters['request'],
                                                         timeout_cb=self.request_timeout)):
            self.tasks.append(self._loop.create_task(task))

    async def request_timeout(self, timeout):
        self._options['logger'].info('request timeout after {:g}s'.format(timeout))

    async def keepalive_timeout(self, timeout):
        self._options['logger'].info('keepalive timeout after {:g}s'.format(timeout))

    async def send_timeout(self, timeout):
        self._options['logger'].info('send timeout after {:g}s'.format(timeout))

    async def set_timeout(self, waiter, timeout=30, timeout_cb=None):
        timer = self._loop.call_at(self._loop.time() + timeout, waiter.cancel)

        try:
            return await waiter
        except asyncio.CancelledError:
            if self._transport is not None:
                if callable(timeout_cb):
                    await timeout_cb(timeout)

                if self._transport is not None and not self._transport.is_closing():
                    self._transport.abort()
        finally:
            timer.cancel()

    async def put_to_queue(self, data, queue=None, transport=None, rate=1048576, buffer_size=16 * 1024):
        data_size = len(data)

        if data_size >= 2 * buffer_size:
            mv = memoryview(data)

            while mv and queue is not None:
                queue.put_nowait(mv[:buffer_size].tobytes())
                await asyncio.sleep(1 / (rate / max(queue.qsize(), 1) / mv[:buffer_size].nbytes))
                mv = mv[buffer_size:]

        elif data != b'' and queue is not None:
            queue.put_nowait(data)
            await asyncio.sleep(1 / (rate / max(queue.qsize(), 1) / data_size))

        if transport is not None and self._request is not None:
            if self._request.http_upgrade:
                transport.resume_reading()
                return

            self._request.body_size += data_size

            if self._request.content_length > -1 and self._request.body_size >= self._request.content_length and queue is not None:
                queue.put_nowait(None)
            elif self._request.body_size < self._options['client_max_body_size']:
                transport.resume_reading()
            else:
                if self._queue[1] is not None:
                    self._request.http_keepalive = False
                    self._queue[1].put_nowait(None)

                self._options['logger'].info('payload too large')

    async def header_received(self, request, response):
        return

    async def handle_exception(self, exc, request, response):
        if request is None or response is None:
            return

        self._options['logger'].error(': '.join(
            (request.path.decode(encoding='latin-1'), exc.__class__.__name__, str(exc))
        ), exc_info={True: exc, False: False}[self._options['debug']])

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

    async def _handle_request_header(self, data, header_size):
        self._data = None

        if self._header.parse(data, header_size=header_size, excludes=[b'proxy']).is_request:
            self._request = HTTPRequest(self)
            self._response = HTTPResponse(self._request)

            try:
                if b'connection' in self._request.headers:
                    if self._request.headers[b'connection'].lower().find(b'close') == -1:
                        self._request.http_keepalive = True
                elif self._request.version == b'1.1':
                    self._request.http_keepalive = True

                if self._request.method in (b'POST', b'PUT', b'PATCH'):
                    if b'content-type' in self._request.headers:
                        self._request.content_type = self._request.headers[b'content-type'].lower()

                    if b'content-length' in self._request.headers:
                        self._request.content_length = int(self._request.headers[b'content-length'])

                    if b'expect' in self._request.headers and self._request.headers[b'expect'].lower() == b'100-continue':
                        if self._request.content_length > self._options['client_max_body_size']:
                            if self._queue[1] is not None:
                                self._queue[1].put_nowait(
                                    b'HTTP/%s 417 Expectation Failed\r\nConnection: close\r\n\r\n' % self._request.version
                                )
                                self._request.http_keepalive = False
                                self._queue[1].put_nowait(None)

                            return

                        if self._queue[1] is not None:
                            self._request.http_continue = True
                            self._queue[1].put_nowait(b'HTTP/%s 100 Continue\r\n\r\n' % self._request.version)
                    elif self._request.content_length > self._options['client_max_body_size']:
                        if self._queue[1] is not None:
                            self._queue[1].put_nowait(
                                b'HTTP/%s 413 Payload Too Large\r\nConnection: close\r\n\r\n' % self._request.version
                            )
                            self._request.http_keepalive = False
                            self._queue[1].put_nowait(None)

                        return

                    await self.put_to_queue(
                        data[header_size + 4:], queue=self._queue[0], transport=self._transport, rate=self._options['upload_rate']
                    )

                await self.header_received(self._request, self._response)
            except Exception as exc:
                await self.handle_exception(exc, self._request, self._response)
        else:
            if self._queue[1] is not None:
                self._queue[1].put_nowait(None)

            self._options['logger'].info('bad request: not a request')

    def data_received(self, data):
        if self._data is not None:
            self._data.extend(data)
            header_size = self._data.find(b'\r\n\r\n')

            if -1 < header_size <= 8192:
                self._transport.pause_reading()

                for i in self._timeout_waiters:
                    if i != 'send' and not self._timeout_waiters[i].done():
                        self._timeout_waiters[i].set_result(None)

                self.tasks.append(self._loop.create_task(self._handle_request_header(self._data, header_size)))
            elif header_size > 8192:
                self._options['logger'].info('request header too large')
                self._transport.abort()
            elif not (header_size == -1 and len(self._data) <= 8192):
                self._options['logger'].info('bad request')
                self._transport.abort()

            return

        self._transport.pause_reading()
        self._loop.create_task(
            self.put_to_queue(data, queue=self._queue[0], transport=self._transport, rate=self._options['upload_rate'])
        )

    def eof_received(self):
        self._queue[0].put_nowait(None)

    def resume_writing(self):
        self._timeout_waiters['send'].set_result(None)

    async def _send_data(self):
        while self._queue[1] is not None:
            try:
                data = await self._queue[1].get()
                self._queue[1].task_done()

                if data is None:
                    if self._request is not None:
                        if self._request.http_keepalive and self._data is None:
                            for i, task in enumerate(self.tasks):
                                try:
                                    exc = task.exception()

                                    if exc:
                                        self._options['logger'].error(': '.join(
                                            (exc.__class__.__name__, str(exc))
                                        ), exc_info={True: exc, False: False}[self._options['debug']])

                                    del self.tasks[i]
                                except asyncio.InvalidStateError:
                                    pass

                            if not self._request.http_continue:
                                self._data = bytearray()
                                self._request.clear_body()

                            self._timeout_waiters['keepalive'] = self._loop.create_future()

                            self.tasks.append(self._loop.create_task(self.set_timeout(self._timeout_waiters['keepalive'],
                                                                                      timeout_cb=self.keepalive_timeout)))
                            self._transport.resume_reading()
                            continue

                        self._request.clear_body()

                    if self._transport.can_write_eof():
                        self._transport.write_eof()

                    self._transport.close()
                    return

                write_buffer_size = self._transport.get_write_buffer_size()
                low, high = self._transport.get_write_buffer_limits()

                if write_buffer_size > high:
                    self._options['logger'].info(
                        '{:d} exceeds the current watermark limits (high={:d}, low={:d})'.format(write_buffer_size, high, low)
                    )
                    self._timeout_waiters['send'] = self._loop.create_future()

                    await self.set_timeout(self._timeout_waiters['send'], timeout_cb=self.send_timeout)

                self._transport.write(data)
            except Exception as exc:
                if self._transport is not None:
                    self._transport.abort()

                raise exc

    def connection_lost(self, exc):
        for task in self.tasks:
            try:
                exc = task.exception()

                if exc:
                    self._options['logger'].error(': '.join(
                        (exc.__class__.__name__, str(exc))
                    ), exc_info={True: exc, False: False}[self._options['debug']])
            except asyncio.InvalidStateError:
                task.cancel()

        for i in (0, 1):
            while not self._queue[i].empty():
                self._queue[i].get_nowait()
                self._queue[i].task_done()

        self._options['_pool'].put({
            'queue': self._queue,
            'header': self._header
        })

        self._transport = None
        self._queue = (None, None)
        self._request = None
        self._response = None
        self._data = None
