# Copyright (c) 2023 nggit

import asyncio

from urllib.parse import quote_from_bytes, unquote_to_bytes

from .contexts import ConnectionContext
from .http_exceptions import (
    HTTPException,
    BadRequest,
    InternalServerError,
    RequestTimeout,
    WebSocketException,
    WebSocketServerClosed
)
from .http_parser import ParseHeader
from .http_request import HTTPRequest
from .http_response import HTTPResponse
from .queue import Queue
from .websocket import WebSocket

_DEFAULT_QUEUE = (None, None)


class HTTPProtocol(asyncio.Protocol):
    __slots__ = ('globals',
                 'context',
                 'options',
                 'loop',
                 'logger',
                 'fileno',
                 'queue',
                 'request',
                 'response',
                 'handler',
                 '_watermarks',
                 '_header_buf',
                 '_waiters')

    def __init__(self, context, loop=None, logger=None, **kwargs):
        self.globals = context  # a worker-level context
        self.context = ConnectionContext()
        self.options = kwargs
        self.loop = loop
        self.logger = logger
        self.fileno = -1
        self.queue = _DEFAULT_QUEUE
        self.request = None
        self.response = None
        self.handler = None

        self._watermarks = {'high': 65536, 'low': 8192}
        self._header_buf = bytearray()
        self._waiters = {}

    @property
    def transport(self):
        return self.context.transport

    @property
    def tasks(self):
        return self.context.tasks

    def add_close_callback(self, callback):
        self.tasks.add(callback)

    def create_background_task(self, coro):
        task = self.loop.create_task(coro)

        self.globals.tasks.add(task)
        task.add_done_callback(self.globals.tasks.discard)

        return task

    def create_task(self, coro):
        task = self.loop.create_task(coro)

        self.tasks.add(task)
        task.add_done_callback(self.handle_task_done)

        return task

    def handle_task_done(self, task):
        self.tasks.discard(task)

        if not task.cancelled():
            exc = task.exception()

            if exc:
                self.print_exception(exc, 'handle_task_done')

    def connection_made(self, transport):
        self.context.update(transport=transport)
        self.fileno = self.context.socket.fileno()

        try:
            self.queue = self.globals.queues.pop(self.fileno)
        except KeyError:
            self.queue = [Queue(), Queue()]

        self._waiters['request'] = self.loop.create_future()

        self.add_close_callback(
            self.create_background_task(self._send_data()).cancel
        )
        self.add_close_callback(self.create_background_task(
            self.set_timeout(self._waiters['request'],
                             timeout=self.options['request_timeout'],
                             timeout_cb=self.request_timeout)
        ).cancel)

    def abort(self, exc=None):
        if self.transport is not None and not self.transport.is_closing():
            self.transport.abort()

            if exc:
                self.print_exception(exc, 'abort')

    def close(self):
        if self.transport is not None and not self.transport.is_closing():
            if self.transport.can_write_eof():
                self.transport.write_eof()

            self.transport.close()

    async def request_timeout(self, timeout):
        self.logger.info('request timeout after %gs', timeout)

    async def keepalive_timeout(self, timeout):
        self.logger.info('keepalive timeout after %gs', timeout)

    async def send_timeout(self, timeout):
        self.logger.info('send timeout after %gs', timeout)

    async def set_timeout(self, waiter, timeout=30, timeout_cb=None):
        timer = self.loop.call_at(self.loop.time() + timeout, waiter.cancel)

        try:
            return await waiter
        except asyncio.CancelledError:
            if self.transport is not None:
                try:
                    if callable(timeout_cb):
                        await timeout_cb(timeout)
                finally:
                    self.abort()
        finally:
            timer.cancel()

    async def put_to_queue(self, data, queue=None, transport=None,
                           rate=1048576, buffer_size=16 * 1024):
        mv = memoryview(data)

        while mv and queue is not None:
            queue.put_nowait(mv[:buffer_size].tobytes())
            queue_size = queue.qsize()

            if queue_size > self.options['max_queue_size']:
                self.logger.error('%d exceeds the value of max_queue_size',
                                  queue_size)
                self.abort()
                return

            await asyncio.sleep(1 / (rate / max(queue_size, 1) /
                                     mv[:buffer_size].nbytes))
            mv = mv[buffer_size:]

        if transport is not None and self.request is not None:
            if self.request.upgraded:
                transport.resume_reading()
                return

            self.request.body_size += len(data)

            if (b'content-length' in self.request.headers and
                    self.request.body_size >= self.request.content_length and
                    queue is not None):
                queue.put_nowait(None)
            elif self.request.body_size < self.options['client_max_body_size']:
                transport.resume_reading()
            else:
                if self.queue[1] is not None:
                    self.request.http_keepalive = False
                    self.queue[1].put_nowait(None)

                self.logger.info('payload too large')

    async def headers_received(self):
        raise NotImplementedError

    async def handle_error_500(self, exc):
        raise NotImplementedError

    def handler_timeout(self):
        if (self.request is None or self.request.upgraded or
                self.handler is None):
            return

        self.handler.cancel()
        self.logger.error('handler timeout after %gs. consider increasing '
                          'the value of app_handler_timeout',
                          self.options['app_handler_timeout'])

    def print_exception(self, exc, *args):
        self.logger.error(
            ': '.join((*args, exc.__class__.__name__, str(exc))),
            exc_info=self.options['debug'] and exc
        )

    async def handle_exception(self, exc):
        if self.request is None or self.response is None:
            self.abort(exc)  # it's here for redundancy
            return

        if not isinstance(exc, asyncio.CancelledError):
            self.print_exception(
                exc, quote_from_bytes(unquote_to_bytes(self.request.path))
            )

        # WebSocket
        if isinstance(exc, WebSocketException):
            if isinstance(exc, WebSocketServerClosed):
                data = WebSocket.create_frame(
                    exc.code.to_bytes(2, byteorder='big'), opcode=8
                )
                await self.response.send(data)

            if self.response is not None:
                self.response.close(keepalive=True)
            return

        # HTTP
        if self.response.headers_sent():
            self.response.close()
            return

        if isinstance(exc, TimeoutError):
            exc = RequestTimeout(cause=exc)
        elif not isinstance(exc, HTTPException):
            exc = InternalServerError(cause=exc)

        self.response.headers.clear()
        self.response.set_status(exc.code, exc.message)
        self.response.set_content_type(exc.content_type)
        data = b''

        try:
            data = await self.handle_error_500(exc) or data
        finally:
            if isinstance(data, str):
                encoding = 'utf-8'

                for v in exc.content_type.split(';', 100):
                    v = v.lstrip()

                    if v.startswith('charset='):
                        encoding = v[8:].strip() or encoding
                        break

                data = data.encode(encoding)

            await self.response.end(data, keepalive=False)

    async def _handle_request(self, data, header_size):
        header = ParseHeader(
            data, header_size=header_size, excludes=[b'proxy']
        )

        if not header.is_request:
            if self.queue[1] is not None:
                self.queue[1].put_nowait(None)

            self.logger.info('bad request: not a request')
            return

        self.request = HTTPRequest(self, header)
        self.response = HTTPResponse(self.request)

        try:
            if b'connection' in self.request.headers:
                if b',close,' not in (b',' +
                                      self.request.headers[b'connection']
                                      .replace(b' ', b'').lower() + b','):
                    self.request.http_keepalive = True
            elif self.request.version == b'1.1':
                self.request.http_keepalive = True

            if self.request.has_body:
                # assuming a request with a body, such as POST
                if b'content-type' in self.request.headers:
                    # don't lower() content-type, as it may contain a boundary
                    self.request.content_type = (
                        self.request.headers[b'content-type']
                    )

                if b'transfer-encoding' in self.request.headers:
                    if self.request.version == b'1.0':
                        raise BadRequest

                    self.request.transfer_encoding = (
                        self.request.headers[b'transfer-encoding'].lower()
                    )

                if b'content-length' in self.request.headers:
                    self.request.content_length = int(
                        b'+' + self.request.headers[b'content-length']
                    )

                    if (b'%d' % self.request.content_length !=
                            self.request.headers[b'content-length'] or
                            b'chunked' in self.request.transfer_encoding):
                        raise BadRequest
                elif self.request.version == b'1.0':
                    raise BadRequest

                if (b'expect' in self.request.headers and
                        self.request.headers[b'expect']
                        .lower() == b'100-continue'):
                    # we can handle continue later after the route is found
                    # by checking this state
                    self.request.http_continue = True
            else:
                # because put_to_queue may also resume reading
                # using put_nowait directly won't
                self.queue[0].put_nowait(b'')

            if self.request.has_body or len(data) > header_size + 2:
                # the initial body that accompanies the header
                # or the next request header, if it's a bodyless request
                await self.put_to_queue(
                    data[header_size + 2:],
                    queue=self.queue[0],
                    transport=self.transport,
                    rate=self.options['upload_rate']
                )

            # successfully got header,
            # clear either the request or keepalive timeout
            for key, fut in self._waiters.items():
                if key in ('request',
                           'keepalive') and not fut.done():
                    fut.set_result(None)

            timer = self.loop.call_at(
                self.loop.time() + self.options['app_handler_timeout'],
                self.handler_timeout
            )

            try:
                if self.request is not None and self.response is not None:
                    await self.headers_received()
            finally:
                timer.cancel()
        except (asyncio.CancelledError, Exception) as exc:
            await self.handle_exception(exc)

    async def _receive_data(self, data, waiter):
        await waiter
        await self.put_to_queue(
            data,
            queue=self.queue[0],
            transport=self.transport,
            rate=self.options['upload_rate'],
            buffer_size=self.options['buffer_size']
        )

    def data_received(self, data):
        if not data:
            return

        if self._header_buf is not None:
            self._header_buf.extend(data)
            header_size = self._header_buf.find(b'\r\n\r\n') + 2

            if 1 < header_size <= self.options['client_max_header_size']:
                # this will keep blocking on bodyless requests forever, unless
                # _handle_keepalive is called; indirectly via Response.close
                self.transport.pause_reading()

                self.handler = self.create_background_task(
                    self._handle_request(self._header_buf, header_size)
                )
                self._header_buf = None
            elif header_size > self.options['client_max_header_size']:
                self.logger.info('request header too large')
                self.abort()
            elif not (header_size == 1 and len(self._header_buf) <=
                      self.options['client_max_header_size']):
                self.logger.info('bad request')
                self.abort()

            return

        self.transport.pause_reading()

        if 'receive' in self._waiters:
            waiter = self._waiters['receive']
        elif 'request' in self._waiters:
            waiter = self._waiters['request']
        else:
            waiter = self._waiters['keepalive']

        self._waiters['receive'] = self.create_task(
            self._receive_data(data, waiter)
        )

    def eof_received(self):
        self.queue[0].put_nowait(None)

    def resume_writing(self):
        if 'send' in self._waiters and not self._waiters['send'].done():
            self._waiters['send'].set_result(None)

    def set_watermarks(self, high=65536, low=8192):
        if self.transport is not None:
            self._watermarks['high'] = high
            self._watermarks['low'] = low

            self.transport.set_write_buffer_limits(high=high, low=low)

    async def _send_data(self):
        while self.queue[1] is not None:
            try:
                data = await self.queue[1].get()

                if data is None:
                    # close the transport, unless keepalive is enabled
                    if self.request is not None:
                        if (self.request.http_keepalive and
                                self._header_buf is None):
                            self._handle_keepalive()
                            continue

                        self.request.clear_body()

                    self.close()
                    return

                # send data
                write_buffer_size = self.transport.get_write_buffer_size()

                if write_buffer_size > self._watermarks['high']:
                    self.logger.info(
                        '%d exceeds the current watermark limits '
                        '(high=%d, low=%d)',
                        write_buffer_size,
                        self._watermarks['high'],
                        self._watermarks['low']
                    )
                    self._waiters['send'] = self.loop.create_future()

                    await self.set_timeout(
                        self._waiters['send'],
                        timeout=self.options['keepalive_timeout'],
                        timeout_cb=self.send_timeout
                    )

                    if self.transport is None:
                        return

                self.transport.write(data)
            except asyncio.CancelledError:
                self.close()
                break
            except Exception as exc:
                self.abort(exc)
                break

    def _handle_keepalive(self):
        if 'request' in self._waiters:
            # store this keepalive connection
            self.options['_connections'][self] = None

        if self not in self.options['_connections']:
            self.close()
            self.logger.info(
                'a keepalive connection is kicked out of the list'
            )
            return

        if self.request.http_continue:
            self.request.http_continue = False
        elif self.request.upgraded:
            if 'request' in self._waiters:
                self._waiters['receive'] = self._waiters.pop('request')
            else:
                self.close()
        else:
            # reset. so the next data in data_received will be considered as
            # a fresh http request (not a continuation data)
            self._header_buf = bytearray()
            self.request.clear_body()
            self._waiters.clear()

            self._waiters['keepalive'] = self.loop.create_future()

            self.add_close_callback(self.create_background_task(
                self.set_timeout(self._waiters['keepalive'],
                                 timeout=self.options['keepalive_timeout'],
                                 timeout_cb=self.keepalive_timeout)
            ).cancel)

            while not self.request.has_body and self.queue[0].qsize():
                # this data is supposed to be the next header
                self.data_received(self.queue[0].get_nowait())

        self.transport.resume_reading()

    def connection_lost(self, _):
        if self in self.options['_connections']:
            del self.options['_connections'][self]

        while self.tasks:
            task = self.tasks.pop()

            try:
                if callable(task):
                    # a close callback
                    task()
                    continue

                task.cancel()
            except Exception as exc:
                self.print_exception(exc, 'connection_lost')

        if self.queue is not _DEFAULT_QUEUE:
            if self.queue[0].clear() and self.queue[1].clear():
                self.globals.queues[self.fileno] = self.queue

            self.queue = _DEFAULT_QUEUE

        self.context.update(transport=None, socket=None)
        self.request = None
        self.response = None
        self.handler = None
        self._header_buf = None
