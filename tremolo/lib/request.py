# Copyright (c) 2023 nggit

import asyncio


class Request:
    __slots__ = ('protocol', 'body_size')

    def __init__(self, protocol):
        self.protocol = protocol
        self.body_size = 0

    @property
    def context(self):
        return self.protocol.context

    @property
    def ctx(self):
        return self.protocol.context

    @property
    def transport(self):
        return self.protocol.transport

    def clear_body(self):
        self.body_size = 0

    async def recv(self):
        while self.protocol.queue[0] is not None:
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

                self.protocol.queue[0].task_done()
            except asyncio.CancelledError:
                raise TimeoutError('recv timeout')
            finally:
                timer.cancel()

            if data is None:
                break

            yield data
