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

    def put_nowait(self, item):
        while True:
            try:
                fut = self._getters.popleft()

                if not fut.done():
                    fut.set_result(item)
                    break
            except IndexError:
                self._queue.append(item)
                break

    async def get(self):
        try:
            if not self._getters:
                return self._queue.popleft()
        except IndexError:
            pass

        fut = self._loop.create_future()
        self._getters.append(fut)

        return await fut

    def task_done(self):
        return

    # non-standar
    def clear(self):
        self._queue.clear()
        self._getters.clear()

        return not self._queue and not self._getters
