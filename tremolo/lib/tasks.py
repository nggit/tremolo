# Copyright (c) 2023 nggit

import asyncio


class ServerTasks:
    def __init__(self, tasks, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self._loop = loop
        self._tasks = tasks

    def create(self, coro, timeout=0):
        task = self._loop.create_task(coro)

        if timeout > 0:
            self._loop.call_at(self._loop.time() + timeout, task.cancel)
        else:
            # until the connection is lost
            self._tasks.append(task.cancel)

        return task
