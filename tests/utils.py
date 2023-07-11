__all__ = ('function', 'getcontents', 'chunked_detected', 'valid_chunked',
           'create_dummy_data', 'create_chunked_body', 'create_dummy_body',
           'create_multipart_body', 'logger')

import asyncio  # noqa: E402
import logging  # noqa: E402
import socket  # noqa: E402
import time  # noqa: E402

from functools import wraps  # noqa: E402


def function(coro):
    @wraps(coro)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()

        try:
            return loop.run_until_complete(coro(*args, **kwargs))
        finally:
            loop.close()

    return wrapper


# a simple HTTP client for tests
def getcontents(
        host='localhost',
        port=80,
        method='GET',
        url='/',
        version='1.1',
        headers=[],
        data='',
        raw=b''
        ):
    if raw == b'':
        content_length = len(data)

        if content_length > 0:
            if headers == []:
                headers.append(
                    'Content-Type: application/x-www-form-urlencoded'
                )

            headers.append('Content-Length: {:d}'.format(content_length))

        raw = ('{:s} {:s} HTTP/{:s}\r\nHost: {:s}:{:d}\r\n{:s}\r\n\r\n'
               '{:s}').format(method,
                              url,
                              version,
                              host,
                              port,
                              '\r\n'.join(headers),
                              data).encode('latin-1')

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(5)

        while sock.connect_ex((host, port)) != 0:
            time.sleep(1)

        sock.sendall(raw)

        response_data = bytearray()
        buf = True

        while buf:
            buf = sock.recv(4096)
            response_data.extend(buf)

            header_size = response_data.find(b'\r\n\r\n')
            response_header = response_data[:header_size]

            if header_size > -1:
                if response_header.lower().startswith(
                        'http/{:s} 100 continue'
                        .format(version).encode('latin-1')):
                    del response_data[:]
                    continue

                if method.upper() == 'HEAD':
                    break

                if (
                        b'\r\ntransfer-encoding: chunked' in
                        response_header.lower() and
                        response_data.endswith(b'\r\n0\r\n\r\n')
                        ):
                    break

                if (
                        (b'\r\ncontent-length: %d' %
                            (len(response_data) - header_size - 4)) in
                        response_header.lower()
                        ):
                    break

        return response_header, response_data[header_size + 4:]


def chunked_detected(header):
    return b'\r\ntransfer-encoding: chunked' in header.lower()


def valid_chunked(body):
    if not body.endswith(b'\r\n0\r\n\r\n'):
        return False

    while body != b'0\r\n\r\n':
        i = body.find(b'\r\n')

        if i == -1:
            return False

        try:
            chunk_size = int(body[:i].split(b';')[0], 16)
        except ValueError:
            return False

        del body[:i + 2]

        if body[chunk_size:chunk_size + 2] != b'\r\n':
            return False

        del body[:chunk_size + 2]

    return True


def create_dummy_data(size, head=b'BEGIN', tail=b'END'):
    data = bytearray([255 - byte for byte in (head + tail)])

    return bytearray(head) + (
        data * (max((size - len(head + tail)) // len(data), 1))
    ) + bytearray(tail)


def create_chunked_body(data, chunk_size=16384):
    if isinstance(data, bytes):
        data = bytearray(data)

    body = bytearray()

    while data != b'':
        chunk = data[:chunk_size]

        body.extend(b'%X\r\n%s\r\n' % (len(chunk), chunk))
        del data[:chunk_size]

    return body + b'0\r\n\r\n'


def create_dummy_body(size, chunk_size=0):
    data = create_dummy_data(size)

    if chunk_size <= 1:
        return data

    return create_chunked_body(data, chunk_size)


def create_multipart_body(boundary=b'----MultipartBoundary', **parts):
    body = bytearray()

    for name, data in parts.items():
        body.extend(b'--%s\r\nContent-Length: %d\r\n' % (boundary, len(data)))
        body.extend(b'Content-Disposition: form-data; name="%s"\r\n' %
                    name.encode('latin-1'))
        body.extend(
            b'Content-Type: application/octet-stream\r\n\r\n%s\r\n' % data
        )

    return body + bytearray(b'--%s--\r\n' % boundary)


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s: %(message)s'
)

handler.setFormatter(formatter)
logger.addHandler(handler)
