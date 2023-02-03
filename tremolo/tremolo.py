# Copyright (c) 2023 nggit

import asyncio
import ipaddress
import multiprocessing as mp
import os
import re
import socket
import sys
import time

from copy import deepcopy
from datetime import datetime
from functools import wraps
from urllib.parse import parse_qs

from .lib.tremolo_protocol import TremoloProtocol

class Tremolo(TremoloProtocol):
    def __init__(self, *args, **kwargs):
        if '_handlers' in kwargs:
            super().__init__(*args, **kwargs)

            self._route_handlers = kwargs['_handlers']
            self._server = {
                'name': b'Tremolo',
                'request' : None,
                'response' : None
            }
        else:
            self._listeners = []

            self._route_handlers = {
                0: [
                    (None, self._err_badrequest, dict(status=(400, b'Bad Request'))),
                    (None, self._err_notfound, dict(status=(404, b'Not Found')))
                ],
                1: [
                    (b'^/+(?:\\?.*)?$', self._index, {})
                ],
                '_unindexed': []
            }

    def add_listener(self, port, host=None, **options):
        self._listeners.append((host, port, options))

    def route(self, path):
        def decorator(func):
            @wraps(func)
            def wrapped(**kwargs):
                return func(**kwargs)

            options = {}

            if func.__defaults__ is not None:
                options = dict(zip(
                    func.__code__.co_varnames[:len(func.__defaults__)],
                    func.__defaults__
                ))

            self._add_handler(path, wrapped, options)
            return wrapped

        return decorator

    def errorhandler(self, status):
        def decorator(func):
            @wraps(func)
            def wrapped(**kwargs):
                return func(**kwargs)

            for i, h in enumerate(self._route_handlers[0]):
                if status == h[2]['status'][0]:
                    self._route_handlers[0][i] = (None, wrapped, h[2])
                    break
            return wrapped

        return decorator

    def _add_handler(self, path=r'^/+(?:\?.*)?$', func=None, kwargs={}):
        if path.startswith('^') or path.endswith('$'):
            pattern = path.encode(encoding='latin-1')
            self._route_handlers['_unindexed'].append((pattern, func, kwargs))
        else:
            qs_pos = path.find('?')
            
            if qs_pos > -1:
                path = path[:qs_pos]

            p = path.strip('/')

            if p == '':
                sc = 1
                pattern = self._route_handlers[1][0][0]
                self._route_handlers[sc] = [(pattern, func, kwargs)]
            else:
                sc = p.count('/') + 2
                pattern = r'^/+{:s}(?:/+)?(?:\?.*)?$'.format(p).encode(encoding='latin-1')

                if sc in self._route_handlers:
                    self._route_handlers[sc].append((pattern, func, kwargs))
                else:
                    self._route_handlers[sc] = [(pattern, func, kwargs)]

    def _compile_handlers(self, handlers={}):
        for sc in handlers:
            for i, h in enumerate(handlers[sc]):
                pattern, *handler = h

                if isinstance(pattern, bytes):
                    handlers[sc][i] = (re.compile(pattern), *handler)

    async def _index(self, **server):
        return b'Under construction.'

    async def _err_badrequest(self, **server):
        return b'Bad request.'

    async def _err_notfound(self, **server):
        yield b'<!DOCTYPE html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        yield b'<title>404 Not Found</title>'
        yield b'<style>body { max-width: 600px; margin: 0 auto; padding: 1%; font-family: sans-serif; }</style></head><body>'
        yield b'<h1>Not Found</h1><p>Unable to find handler for %s.</p><hr /><address>%s</address></body></html>' % (
            server['request'].path.replace(b'&', b'&amp;').replace(b'<', b'&lt;').replace(b'>', b'&gt;').replace(b'"', b'&quot;'),
            server['name'])

    async def body_received(self, request, response):
        if request.content_type.find(b'application/x-www-form-urlencoded') > -1:
            request.params['post'] = parse_qs((await request.body()).decode(encoding='latin-1'))

    async def _handle_response(self, func, options={}):
        rate = options.get('rate', self.options['download_rate'])
        buffer_size = options.get('buffer_size', self.options['buffer_size'])
        status = options.get('status', (200, b'OK'))

        if isinstance(status[1], str):
            status = (status[0], status[1].encode(encoding='latin-1'))

        content_type = options.get('content_type', b'text/html')

        if isinstance(content_type, str):
            content_type = content_type.encode(encoding='latin-1')

        self._server['name'] = options.get('server_name', self.options['server_name'])

        if isinstance(self._server['name'], str):
            self._server['name'] = self._server['name'].encode(encoding='latin-1')

        version = self._server['request'].version

        if version != b'1.0':
            version = b'1.1'

        await self._server['response'].write(b'HTTP/%s %d %s\r\nDate: %s\r\nServer: %s\r\n' % (
                                             version,
                                             *status,
                                             datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT').encode(encoding='latin-1'),
                                             self._server['name']), throttle=False)

        no_content = status[0] in (204, 304) or status[0] // 100 == 1
        chunked = version == b'1.1' and self._server['request'].http_keepalive and no_content is False

        if chunked:
            await self._server['response'].write(b'Transfer-Encoding: chunked\r\n', throttle=False)
            fmt = 2, b'%X\r\n%s\r\n'
        else:
            fmt = 1, b'%s'

        agen = func(**self._server)

        try:
            data = await agen.__anext__()

            if no_content:
                await self._server['response'].write(b'Connection: close\r\n\r\n', throttle=False)
            else:
                await self._server['response'].write(b'Content-Type: %s\r\nConnection: keep-alive\r\n\r\n' %
                                                     content_type, throttle=False)

            if not (self._server['request'].method == b'HEAD' or no_content):
                await self._server['response'].write(fmt[1] % (len(data), data)[-fmt[0]:], rate=rate, buffer_size=buffer_size)

                while True:
                    try:
                        data = await agen.__anext__()

                        await self._server['response'].write(fmt[1] % (len(data), data)[-fmt[0]:], rate=rate, buffer_size=buffer_size)
                    except StopAsyncIteration:
                        await self._server['response'].write(fmt[1] % (0, b'')[-fmt[0]:], throttle=False)
                        break
        except AttributeError:
            data = await agen
            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = (*data, 'utf-8')

            if isinstance(data, str):
                data = data.encode(encoding=encoding[0])

            if no_content or data == b'':
                await self._server['response'].write(b'Connection: close\r\n\r\n', throttle=False)
            else:
                if chunked:
                    await self._server['response'].write(b'Content-Type: %s\r\nConnection: keep-alive\r\n\r\n'
                                                         % content_type, throttle=False)
                else:
                    await self._server['response'].write(b'Content-Type: %s\r\nContent-Length: %d\r\nConnection: %s\r\n\r\n'
                                                         % (content_type, len(data), {True: b'keep-alive',
                                                             False: b'close'}[self._server['request'].http_keepalive]), throttle=False)

            if data != b'' and not (self._server['request'].method == b'HEAD' or no_content):
                await self._server['response'].write((fmt[1] + fmt[1]) % (
                                                     *(len(data), data)[-fmt[0]:],
                                                     *(0, b'')[-fmt[0]:]), rate=rate, buffer_size=buffer_size)

        await self._server['response'].write(None)

    async def header_received(self, request, response):
        self._server['request'] = request
        self._server['response'] = response

        if request.is_valid:
            if b'cookie' in request.headers:
                self._server['request'].cookies = parse_qs(
                    request.headers[b'cookie'].replace(b'; ', b'&').replace(b';', b'&').decode(encoding='latin-1')
                )

            qs_pos = request.path.find(b'?')

            if qs_pos > -1:
                path = request.path[:qs_pos]
                self._server['request'].query = parse_qs(request.path[qs_pos + 1:].decode(encoding='latin-1'))
            else:
                path = request.path

            p = path.strip(b'/')

            if p == b'':
                sc = 1
            else:
                sc = p.count(b'/') + 2

            if sc in self._route_handlers:
                for (pattern, func, kwargs) in self._route_handlers[sc]:
                    m = pattern.search(request.path)

                    if m:
                        matches = m.groupdict()

                        if not matches:
                            matches = m.groups()

                        self._server['request'].params['url'] = matches

                        await self._handle_response(func, kwargs)
                        return
            else:
                for i, (pattern, func, kwargs) in enumerate(self._route_handlers['_unindexed']):
                    m = pattern.search(request.path)

                    if m:
                        if sc in self._route_handlers:
                            self._route_handlers[sc].append((pattern, func, kwargs))
                        else:
                            self._route_handlers[sc] = [(pattern, func, kwargs)]

                        matches = m.groupdict()

                        if not matches:
                            matches = m.groups()

                        self._server['request'].params['url'] = matches

                        await self._handle_response(func, kwargs)
                        del self._route_handlers['_unindexed'][i]
                        return

            # not found
            await self._handle_response(self._route_handlers[0][1][1], self._route_handlers[0][1][2])
        else:
            # bad request
            await self._handle_response(self._route_handlers[0][0][1], self._route_handlers[0][0][2])

    async def _serve(self, host, port, **options):
        options['conn'].send(os.getpid())

        if hasattr(socket, 'fromshare'):
            sock = socket.fromshare(options['conn'].recv())
            sock.listen()
        else:
            fd = options['conn'].recv()

            try:
                sock = socket.fromfd(fd, options['family'], socket.SOCK_STREAM)
                sock.listen()
                options['conn'].send(True)
            except Exception as e:
                options['conn'].send(False)
                sock = options['conn'].recv()
                sock.listen()

        server_name = options.get('server_name', b'Tremolo')

        if isinstance(server_name, str):
            server_name = server_name.encode(encoding='latin-1')

        if isinstance(host, str):
            host = host.encode(encoding='latin-1')

        server = await self._loop.create_server(
            lambda : self.__class__(loop=self._loop,
                                    download_rate=options.get('download_rate', 1048576),
                                    upload_rate=options.get('upload_rate', 1048576),
                                    buffer_size=options.get('buffer_size', 16 * 1024),
                                    client_max_body_size=options.get('client_max_body_size', 2 * 1048576),
                                    server_name=server_name,
                                    _handlers=options['handlers']), sock=sock)

        sys.stdout.buffer.write(b'%s (pid %d) is started at %s port %d' % (server_name, os.getpid(), host, port))
        print()

        process_num = 1

        # serve forever
        while True:
            try:
                # ping parent process
                options['conn'].send(None)

                for i in range(2 * process_num):
                    await asyncio.sleep(1)

                    if options['conn'].poll():
                        break

                process_num = options['conn'].recv()
            except (BrokenPipeError, EOFError):
                server.close()
                break

    def _worker(self, host, port, **kwargs):
        self._compile_handlers(kwargs['handlers'])

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._serve(host, port, **kwargs))
        finally:
            self._loop.close()

    def run(self, host, port=0, reuse_port = True, worker_num=1, **kwargs):
        default_host = host
        self.add_listener(port, host=host, **kwargs)

        try:
            worker_num = min(worker_num, len(os.sched_getaffinity(0)))
        except AttributeError:
            worker_num = min(worker_num, os.cpu_count() or 1)

        processes = []

        for host, port, options in self._listeners:
            if host is None:
                host = default_host

            try:
                sock = socket.socket({4: socket.AF_INET,
                                      6: socket.AF_INET6
                                      }[ipaddress.ip_address(host).version], socket.SOCK_STREAM)
            except ValueError:
                sock = socket.socket(type=socket.SOCK_STREAM)

            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, {True: getattr(socket, 'SO_REUSEPORT', socket.SO_REUSEADDR),
                                                False: socket.SO_REUSEADDR
                                                }[options.get('reuse_port', reuse_port)], 1)
            sock.bind((host, port))
            sock.set_inheritable(True)

            for _ in range(options.get('worker_num', worker_num)):
                parent_conn, child_conn = mp.Pipe()
                args = (host, port)

                p = mp.Process(target=self._worker,
                               args=args,
                               kwargs=dict(options, conn=child_conn, family=sock.family, handlers=deepcopy(self._route_handlers)))

                p.start()
                child_pid = parent_conn.recv()

                if hasattr(sock, 'share'):
                    parent_conn.send(sock.share(child_pid))
                else:
                    parent_conn.send(sock.fileno())

                    if parent_conn.recv() is False:
                        parent_conn.send(sock)

                processes.append((parent_conn, p, args, options))

        while True:
            for i, (parent_conn, p, args, options) in enumerate(processes):
                if not p.is_alive():
                    print('A worker process died. Restarting...')

                    parent_conn.close()
                    parent_conn, child_conn = mp.Pipe()
                    p = mp.Process(target=self._worker,
                                   args=args,
                                   kwargs=dict(options, conn=child_conn, family=sock.family, handlers=deepcopy(self._route_handlers)))

                    p.start()
                    pid = parent_conn.recv()

                    if hasattr(sock, 'share'):
                        parent_conn.send(sock.share(pid))
                    else:
                        parent_conn.send(sock.fileno())

                        if parent_conn.recv() is False:
                            parent_conn.send(sock)

                    processes[i] = (parent_conn, p, args, options)

                # response ping from child
                while parent_conn.poll():
                    parent_conn.recv()
                    parent_conn.send(len(processes))

                try:
                    time.sleep(1)
                except KeyboardInterrupt:
                    for parent_conn, p, *_ in processes:
                        sock.close()
                        parent_conn.close()
                        p.terminate()

                        print('pid {:d} terminated'.format(p.pid))
                    return
