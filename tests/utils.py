
import asyncio
import logging

from functools import wraps

__all__ = ['syncify', 'create_dummy_data', 'create_chunked_body',
           'create_dummy_body', 'create_multipart_body', 'logger']


def syncify(coro):
    @wraps(coro)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()

        try:
            return loop.run_until_complete(coro(*args, **kwargs))
        finally:
            loop.close()

    return wrapper


def create_dummy_data(size, head=b'BEGIN', tail=b'END'):
    data = bytearray([255 - byte for byte in (head + tail)])

    return head + (
        data * (max((size - len(head + tail)) // len(data), 1))
    ) + tail


def create_chunked_body(data, chunk_size=16384):
    data = bytearray(data)
    body = bytearray()

    while data != b'':
        chunk = data[:chunk_size]

        body.extend(b'%X\r\n%s\r\n' % (len(chunk), chunk))
        del data[:chunk_size]

    return bytes(body) + b'0\r\n\r\n'


def create_dummy_body(size, chunk_size=0):
    data = create_dummy_data(size)

    if chunk_size <= 1:
        return data

    return create_chunked_body(data, chunk_size)


def create_multipart_body(boundary=b'----MultipartBoundary', **parts):
    body = bytearray(b'PREAMBLE')

    for name, data in parts.items():
        name = name.encode('latin-1')
        body.extend(b'--%s\r\nContent-Length: %d\r\n' % (boundary, len(data)))

        if name.startswith(b'file'):
            body.extend(
                b'Content-Disposition: form-data; '
                b'name="%s"; filename="%s.ext"\r\n' % (name, name)
            )
            body.extend(b'Content-Type: application/octet-stream\r\n')
        else:
            body.extend(
                b'Content-Disposition: form-data; name="%s"\r\n' % name
            )

        body.extend(b'\r\n%s\r\n' % data)

    return bytes(body) + b'--%s--\r\nEPILOGUE' % boundary


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
formatter = logging.Formatter(
    '[%(asctime)s] %(module)s: %(levelname)s: %(message)s'
)

handler.setFormatter(formatter)
logger.addHandler(handler)
