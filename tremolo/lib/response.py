# Copyright (c) 2023 nggit


class Response:
    __slots__ = ('request', '_send_buf')

    def __init__(self, request):
        self.request = request
        self._send_buf = bytearray()

    def close(self):
        if self._send_buf != b'':
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
                del self._send_buf[:len(data)]

                await self.request.protocol.put_to_queue(
                    data, name=1, rate=rate
                )

    def send_nowait(self, data):
        if self.request.protocol.queue:
            self.request.protocol.queue[1].put_nowait(data)
