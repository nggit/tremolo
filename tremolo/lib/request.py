# Copyright (c) 2023 nggit

class Request:
    def __init__(self, protocol):
        self._protocol = protocol

        self._body_size = 0

    @property
    def protocol(self):
        return self._protocol

    @property
    def context(self):
        return self._protocol.context

    def clear_body(self):
        self._body_size = 0

    async def recv_timeout(self, timeout):
        self._protocol.options['logger'].info('recv timeout after {:g}s'.format(timeout))

    async def recv(self):
        while self._protocol.queue[0] is not None:
            cancel_recv_timeout = self._protocol.loop.create_future()
            self._protocol.loop.create_task(self._protocol.set_timeout(cancel_recv_timeout,
                                                                       timeout_cb=self.recv_timeout))

            data = await self._protocol.queue[0].get()
            self._protocol.queue[0].task_done()
            cancel_recv_timeout.set_result(None)

            if data is None:
                break

            yield data

    @property
    def body_size(self):
        return self._body_size

    @body_size.setter
    def body_size(self, value):
        self._body_size = value
