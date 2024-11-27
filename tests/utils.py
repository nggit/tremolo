__all__ = (
    'syncify', 'read_header', 'getcontents',
    'chunked_detected', 'read_chunked', 'valid_chunked',
    'create_dummy_data', 'create_chunked_body',
    'create_dummy_body', 'create_multipart_body', 'logger'
)

import asyncio  # noqa: E402
import logging  # noqa: E402
import socket  # noqa: E402
import time  # noqa: E402

from functools import wraps  # noqa: E402


def syncify(coro):
    @wraps(coro)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()

        try:
            return loop.run_until_complete(coro(*args, **kwargs))
        finally:
            loop.close()

    return wrapper


def read_header(header, key):
    name = b'\r\n%s: ' % key
    values = []
    start = 0

    while True:
        start = header.find(name, start)

        if start == -1:
            break

        start += len(name)
        values.append(header[start:header.find(b'\r\n', start)])

    return values


# a simple HTTP client for tests
def getcontents(host, port, method='GET', url='/', version='1.1', headers=None,
                data='', raw=b'', timeout=10, max_retries=10):
    if max_retries <= 0:
        raise ValueError('max_retries is exceeded, or it cannot be negative')

    method = method.upper().encode('latin-1')
    url = url.encode('latin-1')
    version = version.encode('latin-1')

    if raw == b'':
        if headers is None:
            headers = []

        if data:
            if not headers:
                headers.append(
                    'Content-Type: application/x-www-form-urlencoded'
                )

            headers.append('Content-Length: %d' % len(data))

        raw = b'%s %s HTTP/%s\r\nHost: %s:%d\r\n%s\r\n\r\n%s' % (
            method, url, version, host.encode('latin-1'), port,
            '\r\n'.join(headers).encode('latin-1'), data.encode('latin-1')
        )

    family = socket.AF_INET

    if ':' in host:
        family = socket.AF_INET6

    if host in ('0.0.0.0', '::'):
        host = 'localhost'

    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(timeout)

        while sock.connect_ex((host, port)) != 0:  # server is not ready yet?
            print('getcontents: reconnecting: %s:%d' % (host, port))
            time.sleep(1)

        request_header = raw[:raw.find(b'\r\n\r\n') + 4]
        request_body = raw[raw.find(b'\r\n\r\n') + 4:]

        try:
            sock.sendall(request_header)

            if not (b'\r\nExpect: 100-continue' in request_header or
                    b'\r\nUpgrade:' in request_header):
                sock.sendall(request_body)

            response_data = bytearray()
            response_header = b''
            content_length = -1

            while True:
                if ((content_length != -1 and
                        len(response_data) >= content_length) or
                        response_data.endswith(b'\r\n0\r\n\r\n')):
                    break

                buf = sock.recv(4096)

                if not buf:
                    break

                response_data.extend(buf)

                if response_header:
                    continue

                header_size = response_data.find(b'\r\n\r\n')

                if header_size == -1:
                    continue

                response_header = response_data[:header_size]
                del response_data[:header_size + 4]

                if method == b'HEAD':
                    break

                values = read_header(response_header, b'Content-Length')

                if values:
                    content_length = int(values[0])

                if response_header.startswith(b'HTTP/%s 100 ' % version):
                    sock.sendall(request_body)
                    response_header = b''
                elif response_header.startswith(b'HTTP/%s 101 ' % version):
                    sock.sendall(request_body)

            return response_header, bytes(response_data)
        except OSError:  # retry if either sendall() or recv() fails
            print(
                'getcontents: retry (%d): %s' % (max_retries, request_header)
            )
            time.sleep(1)
            return getcontents(
                host, port, raw=raw, max_retries=max_retries - 1
            )


def chunked_detected(header):
    return b'\r\ntransfer-encoding: chunked' in header.lower()


def read_chunked(data):
    if not data.endswith(b'\r\n0\r\n\r\n'):
        return False

    data = bytearray(data)
    body = bytearray()

    while data != b'0\r\n\r\n':
        i = data.find(b'\r\n')

        if i == -1:
            return False

        try:
            chunk_size = int(data[:i].split(b';')[0], 16)
        except ValueError:
            return False

        del data[:i + 2]

        if data[chunk_size:chunk_size + 2] != b'\r\n':
            return False

        body.extend(data[:chunk_size])
        del data[:chunk_size + 2]

    return body


def valid_chunked(data):
    return read_chunked(data) is not False


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
    '[%(asctime)s] %(module)s: %(levelname)s: %(message)s'
)

handler.setFormatter(formatter)
logger.addHandler(handler)
