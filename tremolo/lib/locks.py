# Copyright (c) 2023 nggit

import asyncio


class ServerLock:
    def __init__(self, locks, executor, name=0, timeout=30, loop=None):
        self.locks = locks
        self.name = name % len(locks)
        self._executor = executor
        self._timeout = timeout
        self._loop = loop or asyncio.get_event_loop()

    def __call__(self, name=0, *, timeout=None):
        if timeout is None:
            timeout = self._timeout

        return self.__class__(self.locks,
                              self._executor,
                              name=name,
                              timeout=timeout,
                              loop=self._loop)

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        self.release()

    async def acquire(self, timeout=None):
        if timeout is None:
            timeout = self._timeout

        fut = self._executor.submit(self.locks[self.name].acquire,
                                    args=(True, timeout),
                                    name=self.name)
        timer = self._loop.call_at(self._loop.time() + timeout, fut.cancel)

        try:
            result = await fut
        except asyncio.CancelledError:
            result = False
        finally:
            timer.cancel()

        if not result:
            raise TimeoutError

    def release(self):
        try:
            self.locks[self.name].release()
        except ValueError:
            pass
