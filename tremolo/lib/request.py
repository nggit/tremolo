# Copyright (c) 2023 nggit

class Request:
    def __init__(self, protocol):
        self._protocol = protocol
        self._loop = self._protocol.loop

        self._body_size = 0

    def clear_body(self):
        self._body_size = 0

    async def recv_timeout(self, timeout):
        self._protocol.options['logger'].info('recv timeout after {:g}s'.format(timeout))

    async def recv(self):
        while self._protocol.queue[0] is not None:
            cancel_recv_timeout = self._loop.create_future()
            self._loop.create_task(self._protocol.set_timeout(cancel_recv_timeout,
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
