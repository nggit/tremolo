# Copyright (c) 2023 nggit

import asyncio

from .contexts import RequestContext


class Request:
    __slots__ = ('protocol', 'context', 'body_size')

    def __init__(self, protocol):
        self.protocol = protocol
        self.context = RequestContext()
        self.body_size = 0

    @property
    def server(self):
        if self.protocol is None:
            raise RuntimeError('protocol object has been closed')

        return self.protocol

    @property
    def ctx(self):
        return self.context

    @property
    def transport(self):
        return self.server.context.transport

    @property
    def socket(self):
        return self.transport.get_extra_info('socket')

    @property
    def client(self):
        return self.server.context.client

    @property
    def is_secure(self):
        return bool(self.transport.get_extra_info('sslcontext'))

    def clear(self):
        self.body_size = 0

        self.context.clear()
        self.protocol = None  # cut off access to the protocol object

    async def recv(self, timeout=None):
        if timeout is None:
            timeout = self.server.options['keepalive_timeout']

        while self.server.queue:
            try:
                data = await self.server.queue[0].get(timeout)
            except asyncio.CancelledError as exc:
                raise TimeoutError('recv timeout') from exc

            if data is None:
                break

            yield data
