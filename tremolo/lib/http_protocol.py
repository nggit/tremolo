# Copyright (c) 2023 nggit

import asyncio
import traceback

from urllib.parse import quote, unquote

from .h1parser import ParseHeader
from .http_exception import (
    HTTPException,
    BadRequest,
    InternalServerError,
    RequestTimeout,
    WebSocketException,
    WebSocketServerClosed
)
from .http_request import HTTPRequest
from .http_response import HTTPResponse
from .websocket import WebSocket


class HTTPProtocol(asyncio.Protocol):
    __slots__ = ('_context',
                 '_options',
                 '_loop',
                 '_logger',
                 '_worker',
                 '_transport',
                 '_queue',
                 '_request',
                 '_response',
                 '_watermarks',
                 '_header_buf',
                 '_waiters')

    def __init__(self, context, loop=None, logger=None, worker=None, **kwargs):
        self._context = context
        self._options = kwargs
        self._loop = loop
        self._logger = logger
        self._worker = worker
        self._transport = None
        self._queue = (None, None)
        self._request = None
        self._response = None
        self._watermarks = {'high': 65536, 'low': 8192}

        self._header_buf = None
        self._waiters = {}

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
    def logger(self):
        return self._logger

    @property
    def worker(self):
        return self._worker

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
        self._queue = self._options['_pools']['queue'].get()

        self._header_buf = bytearray()
        self._waiters['request'] = self._loop.create_future()

        self.tasks.append(self._loop.create_task(self._send_data()).cancel)
        self.tasks.append(self._loop.create_task(self.set_timeout(
            self._waiters['request'],
            timeout=self._options['request_timeout'],
            timeout_cb=self.request_timeout))
        )

    async def request_timeout(self, timeout):
        self._logger.info('request timeout after %gs' % timeout)

    async def keepalive_timeout(self, timeout):
        self._logger.info('keepalive timeout after %gs' % timeout)

    async def send_timeout(self, timeout):
        self._logger.info('send timeout after %gs' % timeout)

    async def set_timeout(self, waiter, timeout=30, timeout_cb=None):
        timer = self._loop.call_at(self._loop.time() + timeout, waiter.cancel)

        try:
            return await waiter
        except asyncio.CancelledError:
            if self._transport is not None:
                try:
                    if callable(timeout_cb):
                        await timeout_cb(timeout)
                finally:
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
        mv = memoryview(data)

        while mv and queue is not None:
            queue.put_nowait(mv[:buffer_size].tobytes())
            await asyncio.sleep(
                1 / (rate / max(queue.qsize(), 1) /
                     mv[:buffer_size].nbytes)
            )
            mv = mv[buffer_size:]

        if transport is not None and self._request is not None:
            if self._request.upgraded:
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

                self._logger.info('payload too large')

    async def header_received(self):
        return

    def print_exception(self, exc, *args):
        self._logger.error(
            ': '.join((*args, exc.__class__.__name__, str(exc))),
            exc_info=self._options['debug'] and exc
        )

    async def handle_exception(self, exc):
        if (self._request is None or self._response is None or
                (self._response.headers_sent() and
                 not self._request.upgraded)):
            return

        self.print_exception(
            exc,
            quote(unquote(self._request.path.decode('latin-1')))
        )

        if isinstance(exc, WebSocketException):
            if isinstance(exc, WebSocketServerClosed):
                await self._response.send(
                    WebSocket.create_frame(
                        exc.code.to_bytes(2, byteorder='big'),
                        opcode=8)
                )

            if self._response is not None:
                self._response.close()
            return

        if isinstance(exc, TimeoutError):
            exc = RequestTimeout(cause=exc)
        elif not isinstance(exc, HTTPException):
            exc = InternalServerError(cause=exc)

        encoding = 'utf-8'

        for v in exc.content_type.split(';'):
            v = v.lstrip()

            if v.startswith('charset='):
                charset = v[len('charset='):].strip()

                if charset != '':
                    encoding = charset

                break

        if self._options['debug']:
            data = b'<ul><li>%s</li></ul>' % '</li><li>'.join(
                traceback.TracebackException.from_exception(exc).format()
            ).encode(encoding)
        else:
            data = str(exc).encode(encoding)

        if self._response is not None:
            self._response.set_status(exc.code, exc.message)
            self._response.set_content_type(exc.content_type)
            await self._response.end(data, keepalive=False)

    async def _handle_request_header(self, data, header_size):
        header = ParseHeader(data,
                             header_size=header_size, excludes=[b'proxy'])

        if not header.is_request:
            if self._queue[1] is not None:
                self._queue[1].put_nowait(None)

            self._logger.info('bad request: not a request')
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

            if self._request.has_body:
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
                    # we can handle continue later after the route is found
                    # by checking this state
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
            for key, fut in self._waiters.items():
                if key in ('request',
                           'keepalive') and not fut.done():
                    fut.set_result(None)

            await self.header_received()
        except Exception as exc:
            await self.handle_exception(exc)

    async def _receive_data(self, data, waiter):
        await waiter

        try:
            self.tasks.remove(waiter)
        except ValueError:
            pass

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

        if self._header_buf is not None:
            self._header_buf.extend(data)
            header_size = self._header_buf.find(b'\r\n\r\n')

            if -1 < header_size <= self._options['client_max_header_size']:
                # this will keep blocking on bodyless requests forever, unless
                # _handle_keepalive is called; indirectly via Response.close
                self._transport.pause_reading()

                self.tasks.append(
                    self._loop.create_task(
                        self._handle_request_header(self._header_buf,
                                                    header_size))
                )

                self._header_buf = None
            elif header_size > self._options['client_max_header_size']:
                self._logger.info('request header too large')
                self._transport.abort()
            elif not (header_size == -1 and len(self._header_buf) <=
                      self._options['client_max_header_size']):
                self._logger.info('bad request')
                self._transport.abort()

            return

        self._transport.pause_reading()

        if 'receive' in self._waiters:
            waiter = self._waiters['receive']
        elif 'request' in self._waiters:
            waiter = self._waiters['request']
        else:
            waiter = self._waiters['keepalive']

        self._waiters['receive'] = self._loop.create_task(
            self._receive_data(data, waiter)
        )
        self.tasks.append(self._waiters['receive'])

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
                        if (self._request.http_keepalive and
                                self._header_buf is None):
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
                    self._logger.info(
                        '%d exceeds the current watermark limits '
                        '(high=%d, low=%d)' % (
                            write_buffer_size,
                            self._watermarks['high'],
                            self._watermarks['low'])
                    )
                    self._waiters['send'] = self._loop.create_future()

                    await self.set_timeout(
                        self._waiters['send'],
                        timeout=self._options['keepalive_timeout'],
                        timeout_cb=self.send_timeout
                    )

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
        if 'request' in self._waiters:
            # store this keepalive connection
            self._options['_connections'][self] = None

        if self not in self._options['_connections']:
            if self._transport.can_write_eof():
                self._transport.write_eof()

            self._transport.close()
            self._logger.info(
                'a keepalive connection is kicked out of the list'
            )
            return

        i = len(self.tasks)

        while i > 0:
            i -= 1

            if callable(self.tasks[i]):
                continue

            try:
                exc = self.tasks[i].exception()

                if exc:
                    self.print_exception(exc)

                del self.tasks[i]
            except asyncio.InvalidStateError:
                pass

        if self._request.http_continue:
            self._request.http_continue = False
        elif not self._request.upgraded:
            # reset. so the next data in data_received will be considered as
            # a fresh http request (not a continuation data)
            self._header_buf = bytearray()
            self._request.clear_body()
            self._waiters.clear()

            self._waiters['keepalive'] = self._loop.create_future()

            self.tasks.append(
                self._loop.create_task(self.set_timeout(
                    self._waiters['keepalive'],
                    timeout=self._options['keepalive_timeout'],
                    timeout_cb=self.keepalive_timeout))
            )

        self._transport.resume_reading()

    def connection_lost(self, exc):
        if self in self._options['_connections']:
            del self._options['_connections'][self]

        while self.tasks:
            task = self.tasks.pop()

            try:
                if callable(task):
                    # even if you put callable objects in self.tasks,
                    # they will be executed when the client is disconnected.
                    # this is useful for the cleanup mechanism.
                    task()
                    continue

                exc = task.exception()

                if exc:
                    self.print_exception(exc)
            except asyncio.InvalidStateError:
                task.cancel()
            except Exception as exc:
                self.print_exception(exc)

        for queue in self._queue:
            if not queue.clear():
                break
        else:
            self._options['_pools']['queue'].put(self._queue)

        self._transport = None
        self._queue = (None, None)
        self._request = None
        self._response = None
        self._header_buf = None
