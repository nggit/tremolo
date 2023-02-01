# Copyright (c) 2023 nggit

import asyncio

from collections import deque


class Queue:
    def __init__(self, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self._loop = loop
        self._queue = deque()
        self._getters = deque()

    def qsize(self):
        return len(self._queue)

    def _wakeup_next(self):
        while True:
            try:
                fut = self._getters.popleft()

                if not fut.done():
                    fut.set_result(None)
                    break
            except IndexError:
                break

    def put_nowait(self, item):
        self._queue.append(item)
        self._wakeup_next()

    async def get(self):
        while True:
            try:
                return self._queue.popleft()
            except IndexError:
                fut = self._loop.create_future()
                self._getters.append(fut)

                if self._queue:
                    self._wakeup_next()

                await fut

    def task_done(self):
        return

    # non-standar
    def clear(self):
        self._queue.clear()
        self._getters.clear()

        return len(self._queue) == 0 and len(self._getters) == 0
