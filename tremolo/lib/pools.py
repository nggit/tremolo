# Copyright (c) 2023 nggit

from collections import deque

from .__queue import Queue


class Pool:
    def __init__(self, pool_size, logger):
        self._pool = deque(maxlen=pool_size)
        self._logger = logger

        for _ in range(pool_size):
            self._pool.append(self.create())

    def create(self):
        return

    def get(self):
        try:
            return self._pool.popleft()
        except IndexError:
            pool_size = len(self._pool) + 1
            self._pool = deque(self._pool, maxlen=pool_size)

            self._logger.info(
                '%s: limit exceeded. pool size has been adjusted to %d' % (
                    self.__class__.__name__, pool_size)
            )
            return self.create()

    def put(self, item):
        self._pool.append(item)


class QueuePool(Pool):
    def create(self):
        return (Queue(), Queue())
