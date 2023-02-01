# Copyright (c) 2023 nggit

import asyncio


class ServerTasks:
    def __init__(self, tasks, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self._loop = loop
        self._tasks = tasks

    def create(self, coro):
        task = self._loop.create_task(coro)
        self._tasks.append(task.cancel)

        return task
