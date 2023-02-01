# Copyright (c) 2023 nggit

import asyncio

from .exceptions import LifespanError, LifespanProtocolUnsupported


class ASGILifespan:
    def __init__(self, app, **kwargs):
        self._loop = kwargs['loop']
        self._logger = kwargs['logger']

        scope = {
            'type': 'lifespan',
            'asgi': {'version': '3.0'}
        }

        self._queue = asyncio.Queue()
        self._task = self._loop.create_task(
            app(scope, self.receive, self.send)
        )
        self._complete = False

    def startup(self):
        self._complete = False

        self._queue.put_nowait({'type': 'lifespan.startup'})
        self._logger.info('lifespan: startup')

    def shutdown(self):
        self._complete = False

        self._queue.put_nowait({'type': 'lifespan.shutdown'})
        self._logger.info('lifespan: shutdown')

    async def receive(self):
        data = await self._queue.get()
        self._queue.task_done()

        return data

    async def send(self, data):
        if data['type'] in ('lifespan.startup.complete',
                            'lifespan.shutdown.complete'):
            self._complete = True
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
        for _ in range(timeout):
            if self._complete:
                return

            try:
                exc = self._task.exception()

                if exc:
                    if isinstance(exc, LifespanError):
                        return exc

                    if isinstance(exc, LifespanProtocolUnsupported):
                        self._logger.info(str(exc))
                    else:
                        self._logger.info(
                            '%s: %s' % (LifespanProtocolUnsupported.message,
                                        str(exc))
                        )

                return
            except asyncio.InvalidStateError:
                await asyncio.sleep(1)

        if not self._complete:
            self._logger.warning(
                'lifespan: timeout after {:g}s'.format(timeout)
            )
