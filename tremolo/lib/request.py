# Copyright (c) 2023 nggit

import asyncio


class Request:
    __slots__ = ('_protocol', 'body_size')

    def __init__(self, protocol):
        self._protocol = protocol

        self.body_size = 0

    @property
    def protocol(self):
        return self._protocol

    @property
    def context(self):
        return self._protocol.context

    @property
    def transport(self):
        return self._protocol.transport

    def clear_body(self):
        self.body_size = 0

    async def recv(self):
        while self._protocol.queue[0] is not None:
            task = self._protocol.loop.create_task(
                self._protocol.queue[0].get()
            )
            timer = self._protocol.loop.call_at(
                self._protocol.loop.time() +
                self._protocol.options['keepalive_timeout'],
                task.cancel
            )

            try:
                await task
                self._protocol.queue[0].task_done()
            except asyncio.CancelledError:
                raise TimeoutError('recv timeout')
            finally:
                timer.cancel()

            data = task.result()

            if data is None:
                break

            yield data
