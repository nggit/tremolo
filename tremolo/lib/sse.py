# Copyright (c) 2023 nggit

from .http_exception import InternalServerError


class SSE:
    def __init__(self, request, response):
        self.request = request
        self.response = response
        self.protocol = request.protocol

        response.set_content_type(b'text/event-stream')
        response.set_header(b'Cache-Control', b'no-cache, must-revalidate')
        response.set_header(b'Expires', b'Thu, 01 Jan 1970 00:00:00 GMT')

    async def send(self, data, event=None, event_id=None, retry=0):
        if isinstance(data, str):
            data = data.strip('\n').encode('utf-8')
        else:
            data = data.strip(b'\n')

        if b'\n' in data:
            data = data.replace(b'\n', b'\ndata: ')

        for name, value in ((b'event', event), (b'id', event_id)):
            if value:
                if isinstance(value, str):
                    value = value.encode('utf-8')

                if b'\n' in value:
                    raise InternalServerError

                data += b'\n%s: %s' % (name, value)

        if retry:
            data += b'\nretry: %d' % retry

        await self.response.write(b'data: %s\n\n' % data)

    async def close(self):
        await self.response.write(b'', throttle=False)

        self.response.close(keepalive=True)
