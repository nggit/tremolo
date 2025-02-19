# Copyright (c) 2023 nggit

import asyncio

from .contexts import ConnectionContext
from .http_exceptions import (
    HTTPException,
    BadRequest,
    ExpectationFailed,
    InternalServerError,
    RequestTimeout
)
from .http_header import HTTPHeader
from .http_request import HTTPRequest
from .http_response import HTTPResponse
from .queue import Queue


class HTTPProtocol(asyncio.Protocol):
    __slots__ = ('globals',
                 'context',
                 'options',
                 'app',
                 'loop',
                 'logger',
                 'fileno',
                 'queue',
                 'handlers',
                 'request',
                 '_watermarks',
                 '_header_buf',
                 '_waiters')

    def __init__(self, app, **kwargs):
        self.globals = app.context  # a worker-level context
        self.context = ConnectionContext()
        self.options = kwargs['options']
        self.app = app
        self.loop = app.loop
        self.logger = app.logger
        self.fileno = -1
        self.queue = None
        self.handlers = set()
        self.request = None

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
        self.fileno = transport.get_extra_info('socket').fileno()

        try:
            self.queue = self.globals.queues.pop(self.fileno)
        except KeyError:
            self.queue = [Queue(), Queue()]

        self._waiters['request'] = self.loop.create_future()

        self.add_close_callback(self.app.create_task(self._send_data()).cancel)
        self.add_close_callback(self.app.create_task(
            self.set_timeout(self._waiters['request'],
                             timeout=self.options['request_timeout'],
                             timeout_cb=self.request_timeout)
        ).cancel)

    def is_closing(self):
        return self.transport is None or self.transport.is_closing()

    def close(self, exc=None):
        if self.is_closing():
            return

        if exc:
            if isinstance(exc, HTTPException):
                self.transport.write(
                    b'HTTP/1.0 %d %s\r\nContent-Type: %s\r\n\r\n' %
                    (exc.code,
                     exc.message.encode(exc.encoding),
                     exc.content_type.encode(exc.encoding))
                )
                self.transport.write(str(exc).encode(exc.encoding))

            self.print_exception(exc, 'close')

        if self.transport.can_write_eof():
            self.transport.write_eof()

        self.transport.close()

    def request_timeout(self, timeout):
        raise RequestTimeout('request timeout after %gs' % timeout)

    def keepalive_timeout(self, timeout):
        self.logger.info('keepalive timeout after %gs', timeout)

    def send_timeout(self, timeout):
        self.logger.info('send timeout after %gs', timeout)

    async def set_timeout(self, waiter, timeout=30, timeout_cb=None):
        timer = self.loop.call_at(self.loop.time() + timeout, waiter.cancel)

        try:
            return await waiter
        except asyncio.CancelledError:
            if not self.is_closing():
                try:
                    if callable(timeout_cb):
                        timeout_cb(timeout)

                    self.close()
                except Exception as exc:
                    self.close(exc)
        finally:
            timer.cancel()

    async def put_to_queue(self, data, name=0, rate=-1, buffer_size=16384):
        if data:
            start = 0

            while start < len(data) and self.queue is not None:
                buf = data[start:start + buffer_size]
                self.queue[name].put_nowait(buf)
                queue_size = self.queue[name].qsize()

                if queue_size > self.options['max_queue_size']:
                    self.logger.error('%d exceeds the value of max_queue_size',
                                      queue_size)
                    self.close()
                    return

                if rate > 0 and queue_size > 0:
                    await asyncio.sleep(1 / (rate / queue_size / len(buf)))

                start += buffer_size
        elif self.queue is not None:
            self.queue[name].put_nowait(data)

        # maybe resume reading, or close
        if (name == 0 and
                self.transport is not None and self.request is not None):
            if not data or self.request.upgraded:
                self.transport.resume_reading()
                return

            self.request.body_size += len(data)

            if (b'content-length' in self.request.headers and
                    self.request.body_size >= self.request.content_length and
                    self.queue is not None):
                self.queue[name].put_nowait(None)
            elif self.request.body_size < self.options['client_max_body_size']:
                if self.request.has_body:
                    self.transport.resume_reading()
            else:
                self.close(BadRequest('payload too large'))

    async def headers_received(self, response):
        raise NotImplementedError

    async def error_received(self, exc):
        raise NotImplementedError

    def handlers_timeout(self):
        if self.request is None or not self.request.upgraded:
            while self.handlers:
                self.handlers.pop().cancel()
                self.logger.error(
                    'handler timeout '
                    '(app_handler_timeout=%g, app_close_timeout=%g)',
                    self.options['app_handler_timeout'],
                    self.options['app_close_timeout']
                )

    def set_handler_timeout(self, timeout):
        if self.handlers:
            return self.loop.call_at(
                self.loop.time() + timeout, self.handlers_timeout
            )

    def print_exception(self, exc, *args):
        self.logger.error(
            ': '.join((*args, exc.__class__.__name__, str(exc))),
            exc_info=self.options['debug'] and exc
        )

    def send_continue(self):
        if self.request is None or not self.request.http_continue:
            return

        if self.request.content_length > self.options['client_max_body_size']:
            raise ExpectationFailed

        self.transport.write(
            b'HTTP/%s 100 Continue\r\n\r\n' % self.request.version
        )
        self.queue[1].put_nowait(None)

    async def _handle_request(self, header):
        self.request = HTTPRequest(self, header)
        response = HTTPResponse(self.request)

        try:
            if b'connection' in self.request.headers:
                for v in self.request.headers[b'connection'].split(b',', 100):
                    if v.strip().lower() == b'close':
                        break
                else:
                    self.globals.connections.add(self)
                    self.request.http_keepalive = True
            elif self.request.version == b'1.1':
                self.globals.connections.add(self)
                self.request.http_keepalive = True

            if self.request.has_body:
                # assuming a request with a body, such as POST
                if b'transfer-encoding' in self.request.headers:
                    if self.request.version == b'1.0':
                        raise BadRequest('unexpected chunked encoding')

                    self.request.transfer_encoding = self.request.headers[
                        b'transfer-encoding'
                    ].lower()

                if b'content-length' in self.request.headers:
                    try:
                        self.request.content_length = int(
                            b'+' + self.request.headers[b'content-length']
                        )
                    except (ValueError, TypeError) as exc:
                        raise BadRequest('bad Content-Length') from exc

                    if (b'%d' % self.request.content_length !=
                            self.request.headers[b'content-length'] or
                            b'chunked' in self.request.transfer_encoding):
                        raise BadRequest

                if (b'expect' in self.request.headers and
                        self.request.headers[b'expect']
                        .lower() == b'100-continue'):
                    # we can handle continue later after the route is found
                    # by checking this state
                    self.request.http_continue = True
            else:
                await self.put_to_queue(b'')

            if self.request.has_body or header.body:
                # the initial body that accompanies the header
                # or the next request header, if it's a bodyless request
                await self.put_to_queue(
                    header.body, rate=self.options['upload_rate']
                )

            # successfully got header,
            # clear either the request or keepalive timeout
            if not self._waiters['request'].done():
                self._waiters['request'].set_result(None)

            timer = self.set_handler_timeout(
                self.options['app_handler_timeout']
            )

            try:
                if self.request is not None:
                    await self.headers_received(response)
            finally:
                timer.cancel()
        except (asyncio.CancelledError, Exception) as exc:
            data = None

            try:
                data = await self.error_received(exc)
            finally:
                await response.handle_exception(exc, data)

    async def _receive_data(self, data, waiter):
        await waiter
        await self.put_to_queue(
            data,
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
                # Response.close is called (resumed in _send_data)
                self.transport.pause_reading()

                header = HTTPHeader(self._header_buf,
                                    header_size=header_size,
                                    excludes=[b'proxy'])

                if header.is_request:
                    task = self.app.create_task(self._handle_request(header))

                    self.handlers.add(task)
                    task.add_done_callback(self.handlers.discard)
                else:
                    self.close(BadRequest('bad request: not a request'))

                self._header_buf = None
            elif header_size > self.options['client_max_header_size']:
                self.close(BadRequest('request header too large'))
            elif not (header_size == 1 and len(self._header_buf) <=
                      self.options['client_max_header_size']):
                self.close(BadRequest('bad request'))

            return

        # resumed in put_to_queue or _send_data
        self.transport.pause_reading()

        if 'receive' in self._waiters:
            waiter = self._waiters['receive']
        else:
            waiter = self._waiters['request']

        self._waiters['receive'] = self.create_task(
            self._receive_data(data, waiter)
        )

    def resume_writing(self):
        if 'send' in self._waiters and not self._waiters['send'].done():
            self._waiters['send'].set_result(None)

    def set_watermarks(self, high=65536, low=8192):
        if self.transport is not None:
            self._watermarks['high'] = high
            self._watermarks['low'] = low

            self.transport.set_write_buffer_limits(high=high, low=low)

    async def _send_data(self):
        while self.queue is not None:
            try:
                data = await self.queue[1].get()

                if data is None:
                    # close the transport, unless keepalive is enabled
                    if self.request is not None:
                        if self.request.http_continue:
                            self.request.http_continue = False
                            self.transport.resume_reading()
                            continue

                        if self.request.http_keepalive:
                            self.request.http_keepalive = False

                            if self in self.globals.connections:
                                await self._handle_keepalive()
                                self.transport.resume_reading()
                                continue

                            self.logger.info(
                                'keepalive connection dropped: %d', self.fileno
                            )

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
                self.close(exc)
                break

    async def _handle_keepalive(self):
        if self.request.upgraded:
            self._waiters.setdefault('receive', self._waiters.pop('request'))
        else:
            if 'receive' in self._waiters:
                # waits for all incoming data to enter the queue
                await self._waiters.pop('receive')

            if self.request.body_size < self.request.content_length:
                raise InternalServerError(
                    'request body was not fully consumed'
                )

            # reset. so the next data in data_received will be considered as
            # a fresh http request (not a continuation data)
            self.request.clear_body()
            self._header_buf = bytearray()

            self._waiters['request'] = self.loop.create_future()

            self.add_close_callback(self.app.create_task(
                self.set_timeout(self._waiters['request'],
                                 timeout=self.options['keepalive_timeout'],
                                 timeout_cb=self.keepalive_timeout)
            ).cancel)

            while not self.request.has_body and self.queue[0].qsize():
                # this data is supposed to be the next header
                self.data_received(self.queue[0].get_nowait())

    def connection_lost(self, _):
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

        if self.queue is not None:
            if self.queue[0].clear() and self.queue[1].clear():
                self.globals.queues[self.fileno] = self.queue

            self.queue = None

        self.context.update(transport=None)
        self.request = None
        self._header_buf = None

        self.set_handler_timeout(self.options['app_close_timeout'])
        self.globals.connections.discard(self)
