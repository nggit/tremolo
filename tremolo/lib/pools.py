# Copyright (c) 2023 nggit

from collections import deque

from .queue import Queue


class ObjectPool:
    def __init__(self, pool_size=1000):
        self._pool = deque(maxlen=pool_size)

        for _ in range(pool_size):
            self._pool.append(ObjectFactory())

    def get(self, default=None):
        try:
            return self._pool.popleft()
        except IndexError:
            return default

    def put(self, item):
        self._pool.append(item)


class ObjectFactory:
    def __init__(self):
        self.queue = (Queue(), Queue())
