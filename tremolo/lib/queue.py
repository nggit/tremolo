# SPDX-License-Identifier: MIT
# Copyright (c) 2023 Anggit Arfanto

import asyncio

from collections import deque


class Queue:
    def __init__(self, loop=None):
        self._loop = loop or asyncio.get_event_loop()
        self.queue = deque()
        self._getters = deque()

    def qsize(self):
        return len(self.queue)

    def put_nowait(self, item):
        while self._getters:
            fut = self._getters.popleft()

            if not fut.done():
                fut.set_result(item)
                return

        self.queue.append(item)

    async def get(self, timeout=None):
        if self._getters:
            await self._getters[-1]

        try:
            return self.queue.popleft()
        except IndexError:
            fut = self._loop.create_future()
            self._getters.append(fut)

            if timeout is not None:
                timer = self._loop.call_at(self._loop.time() + timeout,
                                           fut.cancel)

            try:
                return await fut
            except asyncio.CancelledError:
                try:
                    self._getters.remove(fut)
                except ValueError:
                    pass

                raise
            finally:
                if timeout is not None:
                    timer.cancel()

    def get_nowait(self):
        return self.queue.popleft()
