# Copyright (c) 2023 nggit

import asyncio

from .contexts import RequestContext


class Request:
    __slots__ = ('_protocol', 'context', 'body_size')

    def __init__(self, protocol):
        self._protocol = protocol
        self.context = RequestContext()
        self.body_size = 0

    @property
    def protocol(self):
        if self._protocol is None:
            raise RuntimeError('protocol object has been closed')

        return self._protocol

    @property
    def ctx(self):
        return self.context

    @property
    def transport(self):
        return self.protocol.context.transport

    @property
    def socket(self):
        return self.transport.get_extra_info('socket')

    @property
    def client(self):
        return self.protocol.context.client

    @property
    def is_secure(self):
        return bool(self.transport.get_extra_info('sslcontext'))

    def clear(self):
        self.body_size = 0

        self.context.clear()
        self._protocol = None  # cut off access to the protocol object

    async def recv(self, timeout=None):
        if timeout is None:
            timeout = self.protocol.options['keepalive_timeout']

        while self.protocol.queue:
            try:
                data = await self.protocol.queue[0].get(timeout)
            except asyncio.CancelledError as exc:
                raise TimeoutError('recv timeout') from exc

            if data is None:
                break

            yield data
