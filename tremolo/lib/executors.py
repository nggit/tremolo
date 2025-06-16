# Copyright (c) 2023 nggit

import asyncio
import queue

from functools import wraps
from inspect import isgeneratorfunction
from threading import Thread


def set_result(fut, result):
    if not fut.done():
        fut.set_result(result)


def set_exception(fut, exc):
    if not fut.done():
        fut.set_exception(exc)


class ThreadExecutor(Thread):
    def __init__(self, context, loop=None, **kwargs):
        super().__init__(**kwargs)

        self.context = context
        self.queue = queue.SimpleQueue()
        self.loop = loop or asyncio.get_event_loop()
        self._shutdown = None

    def run(self):
        while self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(  # set the last active thread
                    self.context.__setattr__, 'thread', self
                )
                fut, func, args, kwargs = self.queue.get(timeout=1)
            except queue.Empty:
                continue

            if func is None:
                self.loop.call_soon_threadsafe(self.join)
                self.loop.call_soon_threadsafe(set_result, fut, None)
                break

            try:
                self.loop.call_soon_threadsafe(
                    set_result, fut, func(*args, **kwargs)
                )
            except StopIteration:
                # StopIteration interacts badly with generators
                # and cannot be raised into a Future
                self.loop.call_soon_threadsafe(fut.cancel)
            except BaseException as exc:
                self.loop.call_soon_threadsafe(set_exception, fut, exc)

    def submit(self, func, *args, **kwargs):
        if not self.is_alive():
            raise RuntimeError(
                'calling submit() before start() or after shutdown()'
            )

        if isgeneratorfunction(func):
            gen = func(*args, **kwargs)

            @wraps(func)
            async def wrapper():
                while True:
                    fut = self.loop.create_future()
                    self.queue.put_nowait((fut, gen.__next__, (), {}))

                    try:
                        yield await fut
                    except asyncio.CancelledError:
                        break

            return wrapper()

        if callable(func):
            fut = self.loop.create_future()
            self.queue.put_nowait((fut, func, args, kwargs))

            return fut

        raise TypeError(f'{str(func)} is not generator function or callable')

    def shutdown(self):
        if self._shutdown is None:
            self._shutdown = self.loop.create_future()

            if self.is_alive():
                self.queue.put_nowait((self._shutdown, None, None, None))

        if not self.is_alive():
            set_result(self._shutdown, None)

        return self._shutdown


class MultiThreadExecutor:
    def __init__(self, size=5):
        self.size = size
        self.threads = []
        self.thread = None  # points to the last active thread
        self.counter = 1

    def start(self, prefix='MultiThreadExecutor', **kwargs):
        while len(self.threads) < self.size:
            self.thread = ThreadExecutor(
                self, name=f'{prefix}-{self.counter}', **kwargs
            )
            self.thread.start()
            self.threads.append(self.thread)

            self.counter += 1

    def submit(self, func, args=(), kwargs={}, name=None):
        if self.size == 0 or len(self.threads) < self.size:
            raise RuntimeError('no threads are running or not ready')

        if name is None:
            thread = self.thread
        else:
            thread = self.threads[name % self.size]

        try:
            return thread.submit(func, *args, **kwargs)
        except RuntimeError:  # dead thread found. attempt self-healing
            self.threads.remove(thread)
            self.start()
            raise

    async def shutdown(self):
        self.size = 0

        while self.threads:
            await self.threads.pop().shutdown()
