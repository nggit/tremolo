# Copyright (c) 2023 nggit

import asyncio
import traceback

from datetime import datetime

from .h1parser import ParseHeader
from .http_exception import HTTPException, BadRequest, InternalServerError
from .http_request import HTTPRequest
from .http_response import HTTPResponse


class HTTPProtocol(asyncio.Protocol):
    def __init__(self, context, **kwargs):
        self._context = context
        self._options = kwargs

        try:
            self._loop = kwargs['loop']
        except KeyError:
            self._loop = asyncio.get_event_loop()

        self._transport = None
        self._queue = (None, None)
        self._request = None
        self._response = None
        self._watermarks = {'high': 65536, 'low': 8192}

        self._pool = None
        self._data = None
        self._waiters = None

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
    def request(self):
        return self._request

    @property
    def response(self):
        return self._response

    def connection_made(self, transport):
        self._transport = transport
        self._pool = self._options['_pool'].get()
        self._queue = self._pool['queue']

        self._data = bytearray()
        self._waiters = {'request': self._loop.create_future()}

        self.tasks.append(
            self._loop.create_task(self.set_timeout(
                self._waiters['request'],
                timeout=self._options['request_timeout'],
                timeout_cb=self.request_timeout))
        )

    async def request_timeout(self, timeout):
        self._options['logger'].info(
            'request timeout after {:g}s'.format(timeout)
        )

    async def keepalive_timeout(self, timeout):
        self._options['logger'].info(
            'keepalive timeout after {:g}s'.format(timeout)
        )

    async def send_timeout(self, timeout):
        self._options['logger'].info(
            'send timeout after {:g}s'.format(timeout)
        )

    async def set_timeout(self, waiter, timeout=30, timeout_cb=None):
        timer = self._loop.call_at(self._loop.time() + timeout, waiter.cancel)

        try:
            return await waiter
        except asyncio.CancelledError:
            if self._transport is not None:
                if callable(timeout_cb):
                    await timeout_cb(timeout)

                if (self._transport is not None and
                        not self._transport.is_closing()):
                    self._transport.abort()
        finally:
            timer.cancel()

    async def put_to_queue(
            self,
            data,
            queue=None,
            transport=None,
            rate=1048576,
            buffer_size=16 * 1024
            ):
        data_size = len(data)

        if data_size >= 2 * buffer_size:
            mv = memoryview(data)

            while mv and queue is not None:
                queue.put_nowait(mv[:buffer_size].tobytes())
                await asyncio.sleep(
                    1 / (rate / max(queue.qsize(), 1) /
                         mv[:buffer_size].nbytes)
                )
                mv = mv[buffer_size:]

        elif data != b'' and queue is not None:
            queue.put_nowait(data)
            await asyncio.sleep(
                1 / (rate / max(queue.qsize(), 1) / data_size)
            )

        if transport is not None and self._request is not None:
            if self._request.http_upgrade:
                transport.resume_reading()
                return

            self._request.body_size += data_size

            if (b'content-length' in self._request.headers and
                    self._request.body_size >= self._request.content_length and
                    queue is not None):
                queue.put_nowait(None)
            elif (self._request.body_size <
                    self._options['client_max_body_size']):
                transport.resume_reading()
            else:
                if self._queue[1] is not None:
                    self._request.http_keepalive = False
                    self._queue[1].put_nowait(None)

                self._options['logger'].info('payload too large')

    async def header_received(self):
        return

    def print_exception(self, exc, *args):
        self._options['logger'].error(': '.join(
            (*args, exc.__class__.__name__, str(exc))
        ), exc_info={True: exc, False: False}[self._options['debug']])

    async def handle_exception(self, exc):
        if (self._request is None or self._response is None or
                self._response.header is None):
            return

        self.print_exception(exc, self._request.path.decode('latin-1'))

        encoding = 'utf-8'

        for v in exc.content_type.split(';'):
            v = v.lstrip()

            if v.startswith('charset='):
                charset = v[len('charset='):].strip()

                if charset != '':
                    encoding = charset

                break

        if self.options['debug']:
            data = b'<ul><li>%s</li></ul>' % '</li><li>'.join(
                traceback.TracebackException.from_exception(exc).format()
            ).encode(encoding)
        else:
            data = str(exc).encode(encoding)

        await self._response.send(
            b'HTTP/%s %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
            b'Connection: close\r\n'
            b'Date: %s\r\nServer: %s\r\n\r\n%s' % (
                self._request.version,
                exc.code,
                exc.message.encode('latin-1'),
                exc.content_type.encode('latin-1'),
                len(data),
                datetime.utcnow().strftime(
                    '%a, %d %b %Y %H:%M:%S GMT').encode('latin-1'),
                self._options['server_name'],
                data)
        )

        if self._response is not None:
            self._response.close()

    async def _handle_request_header(self, data, header_size):
        header = ParseHeader(data,
                             header_size=header_size, excludes=[b'proxy'])

        if not header.is_request:
            if self._queue[1] is not None:
                self._queue[1].put_nowait(None)

            self._options['logger'].info('bad request: not a request')
            return

        self._request = HTTPRequest(self, header)
        self._response = HTTPResponse(self._request)

        try:
            if b'connection' in self._request.headers:
                if (b'close' not in self._request.headers[b'connection']
                        .lower()):
                    self._request.http_keepalive = True
            elif self._request.version == b'1.1':
                self._request.http_keepalive = True

            if (b'transfer-encoding' in self._request.headers or
                    b'content-length' in self._request.headers):
                # assuming a request with a body, such as POST
                if b'content-type' in self._request.headers:
                    # don't lower() content-type, as it may contain a boundary
                    self._request.content_type = self._request.headers[b'content-type']  # noqa: E501

                if b'transfer-encoding' in self._request.headers:
                    if self._request.version == b'1.0':
                        raise BadRequest

                    self._request.transfer_encoding = self._request.headers[b'transfer-encoding'].lower()  # noqa: E501

                if b'content-length' in self._request.headers:
                    if b'chunked' in self._request.transfer_encoding:
                        raise BadRequest

                    self._request.content_length = int(
                        self._request.headers[b'content-length']
                    )
                elif self._request.version == b'1.0':
                    raise BadRequest

                if (b'expect' in self._request.headers and
                        self._request.headers[b'expect']
                        .lower() == b'100-continue'):
                    self._request.http_continue = True

                # the initial body that accompanies the header
                await self.put_to_queue(
                    data[header_size + 4:],
                    queue=self._queue[0],
                    transport=self._transport,
                    rate=self._options['upload_rate']
                )

            # successfully got header,
            # clear either the request or keepalive timeout
            for i in self._waiters:
                if i in ('request',
                         'keepalive') and not self._waiters[i].done():
                    self._waiters[i].set_result(None)

            await self.header_received()
        except Exception as exc:
            if not isinstance(exc, HTTPException):
                exc = InternalServerError(cause=exc)

            await self.handle_exception(exc)

    async def _receive_data(self, data, waiter):
        await waiter
        await self.put_to_queue(
            data,
            queue=self._queue[0],
            transport=self._transport,
            rate=self._options['upload_rate'],
            buffer_size=self._options['buffer_size']
        )

    def data_received(self, data):
        if not data:
            return

        if self._data is not None:
            self._data.extend(data)
            header_size = self._data.find(b'\r\n\r\n')

            if -1 < header_size <= 8192:
                self._transport.pause_reading()
                self.tasks.extend([
                    self._loop.create_task(self._send_data()),
                    self._loop.create_task(
                        self._handle_request_header(self._data, header_size)
                    )
                ])

                self._data = None
            elif header_size > 8192:
                self._options['logger'].info('request header too large')
                self._transport.abort()
            elif not (header_size == -1 and len(self._data) <= 8192):
                self._options['logger'].info('bad request')
                self._transport.abort()

            return

        self._transport.pause_reading()

        if 'receive' in self._waiters:
            waiter = self._waiters['receive']
        else:
            waiter = self._waiters['request']

        self._waiters['receive'] = self._loop.create_task(
            self._receive_data(data, waiter)
        )

    def eof_received(self):
        self._queue[0].put_nowait(None)

    def resume_writing(self):
        if 'send' in self._waiters and not self._waiters['send'].done():
            self._waiters['send'].set_result(None)

    def set_watermarks(self, high=65536, low=8192):
        if self._transport is not None:
            self._watermarks['high'] = high
            self._watermarks['low'] = low

            self._transport.set_write_buffer_limits(high=high, low=low)

    async def _send_data(self):
        while self._queue[1] is not None:
            try:
                data = await self._queue[1].get()
                self._queue[1].task_done()

                if data is None:
                    # close the transport, unless keepalive is enabled
                    if self._request is not None:
                        if self._request.http_keepalive and self._data is None:
                            self._handle_keepalive()
                            continue

                        self._request.clear_body()

                    if self._transport.can_write_eof():
                        self._transport.write_eof()

                    self._transport.close()
                    return

                # send data
                write_buffer_size = self._transport.get_write_buffer_size()

                if write_buffer_size > self._watermarks['high']:
                    self._options['logger'].info(
                        '{:d} exceeds the current watermark limits '
                        '(high={:d}, low={:d})'.format(
                            write_buffer_size,
                            self._watermarks['high'],
                            self._watermarks['low'])
                    )
                    self._waiters['send'] = self._loop.create_future()

                    await self.set_timeout(self._waiters['send'],
                                           timeout_cb=self.send_timeout)

                    if self._transport is None:
                        return

                self._transport.write(data)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                if self._transport is not None:
                    self._transport.abort()
                    self.print_exception(exc)

    def _handle_keepalive(self):
        for task in self.tasks[:]:
            if callable(task):
                continue

            try:
                exc = task.exception()

                if exc:
                    self.print_exception(exc)

                self.tasks.remove(task)
            except asyncio.InvalidStateError:
                pass

        if not self._request.http_continue:
            self._data = bytearray()
            self._request.clear_body()

        self._waiters['keepalive'] = self._loop.create_future()

        self.tasks.append(
            self._loop.create_task(self.set_timeout(
                self._waiters['keepalive'],
                timeout=self._options['keepalive_timeout'],
                timeout_cb=self.keepalive_timeout))
        )
        self._transport.resume_reading()

    def connection_lost(self, exc):
        for task in self.tasks:
            if callable(task):
                # even if you put callable objects in self.tasks,
                # they will be executed when the client is disconnected.
                # this is useful for the cleanup mechanism.
                task()
                continue

            try:
                exc = task.exception()

                if exc:
                    self.print_exception(exc)
            except asyncio.InvalidStateError:
                task.cancel()

        self._options['_pool'].put({
            'queue': (asyncio.Queue(), asyncio.Queue())
        })

        self._transport = None
        self._queue = (None, None)
        self._request = None
        self._response = None
        self._data = None
