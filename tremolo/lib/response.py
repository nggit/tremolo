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

        if (buffer_min_size is not None and
                len(self._send_buf) < buffer_min_size):
            self._send_buf.extend(data)
        else:
            await self.request.protocol.put_to_queue(
                self._send_buf + data,
                name=1,
                rate=rate,
                buffer_size=buffer_size
            )

            del self._send_buf[:]

    def send_nowait(self, data):
        if self.request.protocol.queue is not None:
            self.request.protocol.queue[1].put_nowait(data)
