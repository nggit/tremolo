# Copyright (c) 2023 nggit

import asyncio

from .contexts import RequestContext


class Request:
    __slots__ = ('protocol', 'context', 'body_size', 'body_consumed')

    def __init__(self, protocol):
        self.protocol = protocol
        self.context = RequestContext()
        self.body_size = 0
        self.body_consumed = 0

    @property
    def ctx(self):
        return self.context

    @property
    def transport(self):
        return self.protocol.context.transport

    @property
    def socket(self):
        return self.protocol.context.socket

    def clear_body(self):
        self.body_size = 0
        self.body_consumed = 0

    async def recv(self):
        while self.protocol.queue is not None:
            task = self.protocol.loop.create_task(
                self.protocol.queue[0].get()
            )
            timer = self.protocol.loop.call_at(
                self.protocol.loop.time() +
                self.protocol.options['keepalive_timeout'],
                task.cancel
            )

            try:
                data = await task
            except asyncio.CancelledError as exc:
                raise TimeoutError('recv timeout') from exc
            finally:
                timer.cancel()

            if data is None:
                break

            self.body_consumed += len(data)
            yield data
