# Copyright (c) 2023 nggit

class Response:
    def __init__(self, protocol):
        self._protocol = protocol

    async def send(self, data, throttle=True, rate=1048576, buffer_size=16 * 1024):
        if data is None:
            if self._protocol.queue[1] is not None:
                self._protocol.queue[1].put_nowait(None)
        else:
            if throttle:
                await self._protocol.put_to_queue(data, queue=self._protocol.queue[1], transport=None, rate=rate, buffer_size=buffer_size)
            else:
                if self._protocol.queue[1] is not None:
                    self._protocol.queue[1].put_nowait(data)
