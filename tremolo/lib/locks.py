# Copyright (c) 2023 nggit

import asyncio

from concurrent.futures import ThreadPoolExecutor


class ServerLock:
    def __init__(self, locks, name=0, timeout=30, loop=None, executors=None):
        try:
            self.name = name % len(locks)
        except ZeroDivisionError:
            return

        self.locks = locks
        self._timeout = timeout
        self._loop = loop or asyncio.get_event_loop()

        if executors is None:
            executors = {}

        self._executors = executors

        if self.name not in executors:
            self._executors[self.name] = ThreadPoolExecutor(max_workers=1)

    def __call__(self, name=0, timeout=None):
        if timeout is None:
            timeout = self._timeout

        return self.__class__(self.locks,
                              name=name,
                              timeout=timeout,
                              loop=self._loop,
                              executors=self._executors)

    async def __aenter__(self):
        try:
            await self.acquire()
        except TimeoutError:
            self.release()

    async def __aexit__(self, exc_type, exc, tb):
        self.release()

    async def acquire(self, timeout=None):
        if timeout is None:
            timeout = self._timeout

        fut = self._loop.run_in_executor(
            self._executors[self.name],
            self.locks[self.name].acquire, True, timeout)

        timer = self._loop.call_at(self._loop.time() + timeout, fut.cancel)
        result = False

        try:
            result = await fut
        except asyncio.CancelledError:
            pass
        finally:
            timer.cancel()

        if not result:
            raise TimeoutError

    def release(self):
        try:
            self.locks[self.name].release()
        except ValueError:
            pass
