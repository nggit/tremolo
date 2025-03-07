# Copyright (c) 2023 nggit

import asyncio

from collections import deque


class Queue:
    def __init__(self, loop=None):
        self._loop = loop or asyncio.get_event_loop()
        self._queue = deque()
        self._getters = deque()

    def qsize(self):
        return len(self._queue)

    def put_nowait(self, item):
        while self._getters:
            fut = self._getters.popleft()

            if not fut.done():
                fut.set_result(item)
                return

        self._queue.append(item)

    async def get(self, timeout=None):
        if self._getters:
            await self._getters[-1]

        try:
            return self._queue.popleft()
        except IndexError:
            fut = self._loop.create_future()
            self._getters.append(fut)

            if timeout is None:
                return await fut

            timer = self._loop.call_at(self._loop.time() + timeout, fut.cancel)

            try:
                return await fut
            finally:
                timer.cancel()

    def get_nowait(self):
        return self._queue.popleft()

    # non-standar
    def clear(self):
        self._queue.clear()
        self._getters.clear()

        return not self._queue and not self._getters
