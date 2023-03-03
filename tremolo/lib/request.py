# Copyright (c) 2023 nggit

class Request:
    def __init__(self, protocol):
        self._protocol = protocol
        self._loop = self._protocol.loop

    async def recv_finished(self):
        return

    async def recv_started(self):
        return

    async def recv_timeout(self, timeout):
        self._protocol.options['logger'].info('recv timeout after {:d}s'.format(timeout))

    async def recv(self):
        await self.recv_started()

        while self._protocol.queue[0] is not None:
            cancel_recv_timeout = self._loop.create_future()
            self._loop.create_task(self._protocol.set_timeout(cancel_recv_timeout,
                                                              timeout_cb=self.recv_timeout))

            data = await self._protocol.queue[0].get()
            self._protocol.queue[0].task_done()
            cancel_recv_timeout.set_result(None)

            if data is None:
                await self.recv_finished()
                break

            yield data
