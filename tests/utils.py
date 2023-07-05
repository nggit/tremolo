__all__ = ('getcontents', 'chunked_detected',
           'valid_chunked', 'create_dummy_body')

import socket  # noqa: E402
import time  # noqa: E402


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
                        response_header.lower().find(
                            b'\r\ntransfer-encoding: chunked') > -1 and
                        response_data.endswith(b'\r\n0\r\n\r\n')
                        ):
                    break

                if (
                        response_header.lower().find(
                            b'\r\ncontent-length: %d' %
                            (len(response_data) - header_size - 4)) > -1
                        ):
                    break

        return response_header, response_data[header_size + 4:]


def chunked_detected(header):
    return header.lower().find(b'\r\ntransfer-encoding: chunked') > -1


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


def create_dummy_body(size, chunk_size=0):
    data = bytearray(size)

    if chunk_size <= 1:
        return data

    result = bytearray()

    for _ in range(len(data) // chunk_size):
        chunk = data[:chunk_size]
        result.extend(b'%X\r\n%s\r\n' % (len(chunk), chunk))

    return result + b'0\r\n\r\n'
