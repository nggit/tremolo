# Copyright (c) 2023 nggit

import asyncio

from .exceptions import LifespanError, LifespanProtocolUnsupported


class ASGILifespan:
    def __init__(self, app, options):
        self._loop = app.loop
        self._logger = app.logger
        self._options = options

        self._queue = asyncio.Queue()
        self._waiter = self._loop.create_future()
        self._task = self._loop.create_task(self.main(options['app']))

    async def main(self, app):
        try:
            scope = {
                'type': 'lifespan',
                'asgi': {'version': '3.0', 'spec_version': '2.0'},
                'state': self._options['state']
            }

            await app(scope, self.receive, self.send)
        finally:
            self._waiter.cancel()

    def startup(self):
        self._queue.put_nowait({'type': 'lifespan.startup'})
        self._logger.info('lifespan: startup')

    def shutdown(self):
        self._queue.put_nowait({'type': 'lifespan.shutdown'})
        self._logger.info('lifespan: shutdown')

    async def receive(self):
        data = await self._queue.get()
        self._queue.task_done()

        return data

    async def send(self, data):
        if data['type'] in ('lifespan.startup.complete',
                            'lifespan.shutdown.complete'):
            self._waiter.set_result(None)
            self._logger.info(data['type'])
        elif data['type'] in ('lifespan.startup.failed',
                              'lifespan.shutdown.failed'):
            if 'message' in data:
                message = ': %s' % data['message']
            else:
                message = ''

            raise LifespanError('%s%s' % (data['type'], message))
        else:
            raise LifespanProtocolUnsupported

    async def exception(self, timeout=30):
        timer = self._loop.call_at(self._loop.time() + timeout,
                                   self._waiter.cancel)

        try:
            await self._waiter

            self._waiter = self._loop.create_future()
        except asyncio.CancelledError:
            try:
                exc = self._task.exception()

                if exc:
                    if isinstance(exc, LifespanError):
                        return exc

                    if isinstance(exc, LifespanProtocolUnsupported):
                        self._logger.info(exc)
                    else:
                        self._logger.info(
                            '%s: %s',
                            LifespanProtocolUnsupported.message,
                            str(exc) or repr(exc)
                        )
            except asyncio.InvalidStateError:
                self._logger.warning('lifespan: timeout after %gs', timeout)
        finally:
            timer.cancel()
