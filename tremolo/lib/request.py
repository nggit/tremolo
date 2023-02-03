# Copyright (c) 2023 nggit

import asyncio

class Request:
    def __init__(self, protocol):
        self._protocol = protocol
        self._loop = self._protocol.loop

    async def read_finished(self):
        return

    async def read_started(self):
        return

    async def read_timeout(self, timeout):
        print('read timeout after {:d}s'.format(timeout))

    async def read(self):
        await self.read_started()

        while True:
            cancel_read_timeout = self._loop.create_future()
            self._loop.create_task(self._protocol.set_timeout(cancel_read_timeout,
                                                          timeout_cb=self.read_timeout))

            data = await self._protocol.queue[0].get()
            self._protocol.queue[0].task_done()
            cancel_read_timeout.set_result(None)

            if data is None:
                await self.read_finished()
                break

            yield data
