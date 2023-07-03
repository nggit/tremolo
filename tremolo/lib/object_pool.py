# Copyright (c) 2023 nggit

import asyncio


class ObjectPool:
    def __init__(self, pool_size, logger):
        self._pool_size = pool_size
        self._pools = []
        self._logger = logger

        for _ in range(pool_size):
            self._pools.append(self._create())

    def _create(self):
        return {
            'queue': (asyncio.Queue(), asyncio.Queue())
        }

    def get(self):
        try:
            return self._pools.pop()
        except IndexError:
            self._pool_size += 1

            self._logger.info(
                'limit exceeded. pool size has been adjusted to {:d}'
                .format(self._pool_size)
            )
            return self._create()

    def put(self, value):
        if len(self._pools) < self._pool_size:
            self._pools.append(value)
