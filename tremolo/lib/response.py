# Copyright (c) 2023 nggit


class Response:
    __slots__ = ('_protocol',)

    def __init__(self, request):
        self._protocol = request.protocol

    def close(self):
        self.send_nowait(None)

    async def send(
            self,
            data,
            throttle=True,
            rate=1048576,
            buffer_size=16 * 1024, **_
            ):
        if data is None:
            __class__.close(self)
            return

        if not isinstance(data, (bytes, bytearray)):
            raise TypeError('expected None or bytes-like object')

        if throttle:
            await self._protocol.put_to_queue(
                data,
                queue=self._protocol.queue[1],
                transport=None,
                rate=rate,
                buffer_size=buffer_size
            )
        else:
            self.send_nowait(data)

    def send_nowait(self, data):
        if self._protocol.queue[1] is not None:
            self._protocol.queue[1].put_nowait(data)
