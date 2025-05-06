# Copyright (c) 2023 nggit


class Response:
    __slots__ = ('request', '_send_buf')

    def __init__(self, request):
        self.request = request
        self._send_buf = bytearray()

    def close(self):
        if self._send_buf:
            self.send_nowait(self._send_buf[:])
            del self._send_buf[:]

        self.send_nowait(None)

    async def send(self, data, rate=-1,
                   buffer_size=16384, buffer_min_size=None):
        if data is None:
            __class__.close(self)
            return

        if not isinstance(data, (bytes, bytearray)):
            raise TypeError('expected None or bytes-like object')

        self._send_buf.extend(data)

        if buffer_min_size is None or len(self._send_buf) >= buffer_min_size:
            while self._send_buf:
                data = self._send_buf[:buffer_size]

                if await self.request.server.put_to_queue(
                        data, name=1, rate=rate):
                    del self._send_buf[:len(data)]
                else:
                    del self._send_buf[:]
                    self.request.clear()

    def send_nowait(self, data):
        if self.request.server.queue:
            self.request.server.queue[1].put_nowait(data)
