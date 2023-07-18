# Copyright (c) 2023 nggit

import asyncio


class MultiprocessingLock:
    def __init__(self, lock):
        self._lock = lock
        self._delay = 0.01

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        self.release()

    async def acquire(self, timeout=30):
        for _ in range(int(timeout / self._delay)):
            if self._lock.acquire(block=False):
                break

            await asyncio.sleep(self._delay)
        else:
            raise TimeoutError

    def release(self):
        self._lock.release()
