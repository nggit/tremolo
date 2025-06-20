# Copyright (c) 2023 nggit

import asyncio

from tremolo.utils import parse_int
from .contexts import ConnectionContext
from .http_exceptions import (
    HTTPException,
    BadRequest,
    ExpectationFailed,
    RequestTimeout
)
from .http_header import HTTPHeader
from .http_request import HTTPRequest
from .queue import Queue


class HTTPProtocol(asyncio.Protocol):
    __slots__ = ('queue', 'events', 'handlers', '_receive_buf', '_watermarks')

    def __init__(self, app, **kwargs):
        self.app = app
        self.extras = kwargs
        self.loop = app.loop
        self.logger = app.logger
        self.globals = app.context  # a worker-level context
        self.context = ConnectionContext()
        self.lock = kwargs['lock']
        self.fileno = -1
        self.request = None

        self.queue = [Queue(), Queue()]  # IN, OUT
        self.events = {}
        self.handlers = set()
        self._receive_buf = bytearray()
        self._watermarks = {'high': 65536, 'low': 8192}

    @property
    def server(self):  # all properties except those that are slotted
        return self.__dict__

    @property
    def options(self):
        return self.extras['options']

    @property
    def transport(self):
        return self.context.transport

    def add_close_callback(self, callback):
        self.context.tasks.add(callback)

    def add_task(self, task):
        self.context.tasks.add(task)
        task.add_done_callback(self.handle_task_done)

    def create_task(self, coro):
        task = self.loop.create_task(coro)
        self.add_task(task)

        return task

    def handle_task_done(self, task):
        self.context.tasks.discard(task)

        if not task.cancelled():
            exc = task.exception()

            if exc:
                self.print_exception(exc, 'handle_task_done')

    def connection_made(self, transport):
        self.context.update(transport=transport)
        self.fileno = transport.get_extra_info('socket').fileno()

        self.events['request'] = self.loop.create_future()

        self.add_close_callback(self.app.create_task(self._send_data()).cancel)
        self.add_task(self.app.create_task(
            self.set_timeout(self.events['request'],
                             timeout=self.options['request_timeout'],
                             timeout_cb=self.request_timeout)
        ))

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

        try:
            self.transport.write_eof()
        except (OSError, RuntimeError) as exc:
            self.logger.info(exc)
        finally:
            self.add_close_callback(
                self.loop.call_at(self.loop.time() +
                                  self.options['app_close_timeout'],
                                  self.transport.abort).cancel
            )
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

    async def put_to_queue(self, data, name=0, rate=-1):
        if self.queue:
            self.queue[name].put_nowait(data)
            queue_size = self.queue[name].qsize()

            if queue_size <= self.options['max_queue_size']:
                if data and rate > 0 and queue_size > 0:
                    await asyncio.sleep(queue_size * len(data) / rate)

                return True

            self.logger.error('%d exceeds the value of max_queue_size',
                              queue_size)

        self.close()

    async def request_received(self, request, response):
        raise NotImplementedError

    async def error_received(self, exc, response):
        # internal server error
        return await self.app.routes[0][-1][1](request=response.request,
                                               response=response,
                                               exc=exc)

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

    async def _handle_request(self):
        try:
            response = self.request.create_response()

            if b'connection' in self.request.headers:
                if b'close' not in self.request.headers.getlist(b'connection'):
                    self.globals.connections.add(self)
                    self.request.http_keepalive = True
            elif self.request.version == b'1.1':
                self.globals.connections.add(self)
                self.request.http_keepalive = True

            if self.request.has_body:
                # assuming a request with a body, such as POST
                if b'transfer-encoding' in self.request.headers:
                    if self.request.version == b'1.0':
                        raise BadRequest('unexpected Transfer-Encoding')

                if b'content-length' in self.request.headers:
                    if b'chunked' in self.request.transfer_encoding:
                        raise BadRequest

                    try:
                        self.request.content_length = parse_int(
                            self.request.headers[b'content-length']
                        )
                    except ValueError as exc:
                        raise BadRequest('bad Content-Length') from exc

                if (b'expect' in self.request.headers and
                        self.request.headers[b'expect']
                        .lower() == b'100-continue'):
                    # we can handle continue later after the route is found
                    # by checking this state
                    self.request.http_continue = True
            else:
                self.queue[0].put_nowait(b'')

            # successfully got header,
            # clear either the request or keepalive timeout
            if not self.events['request'].done():
                self.events['request'].set_result(None)

            timer = self.set_handler_timeout(
                self.options['app_handler_timeout']
            )

            try:
                await self.request_received(self.request, response)
            finally:
                timer.cancel()
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            if self.request is not None:
                data = None

                try:
                    data = await self.error_received(exc, response)
                finally:
                    await response.handle_exception(exc, data)

    async def _receive_data(self):
        if 'request' in self.events:
            await self.events['request']

        if self.request is None:
            return

        excess = 0

        if not self.request.upgraded:
            self.request.body_size += len(self._receive_buf)

            if self.request.body_size > self.request.content_length > -1:
                excess = self.request.body_size - self.request.content_length

        while len(self._receive_buf) > excess:
            data = self._receive_buf[:min(self.options['buffer_size'],
                                          len(self._receive_buf) - excess)]

            if await self.put_to_queue(data, rate=self.options['upload_rate']):
                del self._receive_buf[:len(data)]
            else:
                del self._receive_buf[:]
                return

        # maybe resume reading, or close
        if self.request is not None:
            del self.events['receive']

            if self.request.upgraded:
                if self in self.globals.connections:
                    self.transport.resume_reading()
            elif self.request.body_size >= self.request.content_length > -1:
                self.queue[0].put_nowait(None)
            elif self.request.body_size < self.options['client_max_body_size']:
                if self.request.has_body:
                    self.transport.resume_reading()
            else:
                self.close(BadRequest('payload too large'))

    def data_received(self, data):
        if not data:
            return

        self._receive_buf.extend(data)

        if self.request is None:
            header_size = self._receive_buf.find(b'\r\n\r\n') + 2

            if 1 < header_size <= self.options['client_max_header_size']:
                header = HTTPHeader(self._receive_buf[:header_size],
                                    header_size=header_size,
                                    excludes=[b'proxy'])
                del self._receive_buf[:header_size + 2]

                if header.is_request:
                    self.request = HTTPRequest(self, header)
                    task = self.app.create_task(self._handle_request())

                    self.handlers.add(task)
                    task.add_done_callback(self.handlers.discard)
                else:
                    self.close(BadRequest('bad request: not a request'))
            elif header_size > self.options['client_max_header_size']:
                self.close(BadRequest('request header too large'))
            elif not (header_size == 1 and len(self._receive_buf) <=
                      self.options['client_max_header_size']):
                self.close(BadRequest('bad request'))

            if self.request is None or not self._receive_buf:
                return

        # resumed in _receive_data or _send_data
        self.transport.pause_reading()

        if 'receive' not in self.events:
            self.events['receive'] = self.create_task(self._receive_data())

    def resume_writing(self):
        if 'send' in self.events and not self.events['send'].done():
            self.events['send'].set_result(None)

    def set_watermarks(self, high=65536, low=8192):
        if self.transport is not None:
            self._watermarks['high'] = high
            self._watermarks['low'] = low

            self.transport.set_write_buffer_limits(high=high, low=low)

    async def _send_data(self):
        try:
            while self.queue:
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
                                if not self.request.upgraded:
                                    await self._handle_keepalive()

                                self.transport.resume_reading()
                                continue

                            self.logger.info(
                                'keepalive connection dropped: %d', self.fileno
                            )

                        del self._receive_buf[:]
                        self.request.clear()

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
                    self.events['send'] = self.loop.create_future()

                    await self.set_timeout(
                        self.events['send'],
                        timeout=self.options['keepalive_timeout'],
                        timeout_cb=self.send_timeout
                    )

                    if self.transport is None:
                        return

                self.transport.write(data)
        except asyncio.CancelledError:
            self.close()
        except Exception as exc:
            self.close(exc)

    async def _handle_keepalive(self):
        if 'receive' in self.events:
            # waits for all incoming data to enter the queue
            await self.events['receive']

        if self.request.has_body:
            if not self.request.eof():
                self.logger.info('request body was not fully consumed')
                self.close()
                return

            if b'transfer-encoding' in self.request.headers:
                self.close()
                return

        self.events['request'] = self.loop.create_future()

        self.add_task(self.app.create_task(
            self.set_timeout(self.events['request'],
                             timeout=self.options['keepalive_timeout'],
                             timeout_cb=self.keepalive_timeout)
        ))

        # reset. so the next data in data_received will be considered as
        # a fresh http request (not a continuation data)
        self.request.clear()
        self.request = None

        if self._receive_buf:
            self.queue[0].put_nowait(self._receive_buf[:])
            del self._receive_buf[:]

        while self.queue[0].qsize():
            # this data is supposed to be the next header
            self.data_received(self.queue[0].get_nowait())

    def connection_lost(self, _):
        while self.context.tasks:
            task = self.context.tasks.pop()

            try:
                if callable(task):
                    # a close callback
                    task()
                    continue

                task.cancel()
            except Exception as exc:
                self.print_exception(exc, 'connection_lost')

        while self.queue:
            self.queue.pop().clear()

        self.request = None

        self.context.clear()
        self.events.clear()
        self._watermarks.clear()

        self.set_handler_timeout(self.options['app_close_timeout'])
        self.globals.connections.discard(self)
