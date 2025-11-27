# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Anggit Arfanto

import asyncio
import socket
import ssl
import time

from .http_response import HTTPResponse

__version__ = '0.0.2'


def capitalize(name):
    return b'-'.join(part.capitalize() for part in name.split(b'-'))


def getfamily(host, port=None):
    if port is None:
        return socket.AF_UNIX, host

    family = socket.AF_INET6 if ':' in host else socket.AF_INET

    if host in ('0.0.0.0', '::'):
        host = 'localhost'

    return family, (host, port)


class Client:
    def __init__(self, host, port=None, *, timeout=30, retries=0, loop=None,
                 ssl=None, server_hostname=None):
        self.loop = loop
        self.host = host
        self.family, self.address = getfamily(host, port)
        self.timeout = timeout or None
        self.retries = retries
        self.ssl = ssl  # can be True, ssl.SSLContext, or None
        self.server_hostname = server_hostname or host
        self.sock = None

    def __enter__(self):
        if self.sock is not None:
            self.sock.close()

        for retries in range(self.retries, -1, -1):
            self.sock = socket.socket(self.family, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)

            try:
                self.sock.connect(self.address)
                break
            except socket.timeout:
                self.sock.close()
                raise
            except OSError:
                self.sock.close()

                if retries == 0:
                    raise

                if self.retries > 0:
                    time.sleep(self.timeout / self.retries)

        if self.ssl:
            if not isinstance(self.ssl, ssl.SSLContext):
                self.ssl = ssl.create_default_context()

            self.sock = self.ssl.wrap_socket(
                self.sock,
                server_hostname=self.server_hostname
            )

        return self

    def __exit__(self, exc_type, exc, tb):
        self.sock.close()

    async def __aenter__(self):
        if self.loop is None:
            self.loop = asyncio.get_event_loop()

        if self.sock is not None:
            self.sock.close()

        for retries in range(self.retries, -1, -1):
            self.sock = socket.socket(self.family, socket.SOCK_STREAM)
            self.sock.setblocking(False)

            task = self.loop.create_task(
                self.loop.sock_connect(self.sock, self.address)
            )
            timer = self.loop.call_later(self.timeout, task.cancel)

            try:
                await task
                break
            except asyncio.CancelledError as exc:
                self.sock.close()
                raise socket.timeout from exc
            except OSError:
                self.sock.close()

                if retries == 0:
                    raise

                if self.retries > 0:
                    await asyncio.sleep(self.timeout / self.retries)
            finally:
                timer.cancel()

        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.sock.close()

    def recv(self, n):
        if self.sock.gettimeout() == 0:
            return self.loop.sock_recv(self.sock, n)

        buf = bytearray()

        while len(buf) < n:
            data = self.sock.recv(n - len(buf))

            if data == b'':
                break

            buf.extend(data)

        return bytes(buf)

    def sendall(self, data):
        if self.sock.gettimeout() == 0:
            return self.loop.sock_sendall(self.sock, data)

        return self.sock.sendall(data)


class HTTPClient(Client):
    def __init__(self, host, port=None, **kwargs):
        super().__init__(host, port, **kwargs)

        if port is None:
            host = 'localhost'
        else:
            host = '%s:%d' % self.address

        self.headers = [
            b'Host: ' + host.encode('latin-1'),
            b'User-Agent: netizen/' + __version__.encode('latin-1'),
            b'Accept: */*'
        ]

    def update_cookie(self, value):
        name, _ = value.split(b'=', 1)

        for i, header in enumerate(self.headers):
            if header.startswith(b'Cookie: %s=' % name):
                self.headers[i] = b'Cookie: %s' % value
                break
        else:
            self.headers.append(b'Cookie: %s' % value)

    def send(self, line, *args, body=b''):
        headers = self.headers.copy()

        for arg in args:
            name, value = arg.split(b':', 1)
            name = capitalize(name)

            if name == b'Host':
                headers[0] = b'Host: ' + value.strip(b' \t')
            elif name == b'User-Agent':
                headers[1] = b'User-Agent: ' + value.strip(b' \t')
            else:
                headers.append(name + b': ' + value.strip(b' \t'))

        if body and not args:
            headers.append(b'Content-Type: application/x-www-form-urlencoded')
            headers.append(b'Content-Length: %d' % len(body))

        header = b'\r\n'.join(headers)
        defer = body == b'' and (b'\r\nContent-Length:' in header or
                                 b'\r\nTransfer-Encoding:' in header)

        return HTTPResponse(self, line, header, body, defer=defer)

    def end(self):
        return HTTPResponse(self)
