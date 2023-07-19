# Copyright (c) 2023 nggit

import asyncio


class MultiprocessingLock:
    def __init__(self, lock):
        self._lock = lock
        self._factor = 100

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        self.release()

    async def acquire(self, timeout=30):
        for _ in range(timeout * self._factor):
            if self._lock.acquire(block=False):
                break

            await asyncio.sleep(1 / self._factor)
        else:
            raise TimeoutError

    def release(self):
        try:
            self._lock.release()
        except (AssertionError, ValueError):
            pass
