# Copyright (c) 2023 nggit


class Request:
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

    async def recv_timeout(self, timeout):
        self._protocol.options['logger'].info(
            'recv timeout after {:g}s'.format(timeout)
        )

    async def recv(self):
        while self._protocol.queue[0] is not None:
            recv_waiter = self._protocol.loop.create_future()
            self._protocol.loop.create_task(
                self._protocol.set_timeout(recv_waiter,
                                           timeout_cb=self.recv_timeout)
            )

            data = await self._protocol.queue[0].get()
            self._protocol.queue[0].task_done()
            recv_waiter.set_result(None)

            if data is None:
                break

            yield data
