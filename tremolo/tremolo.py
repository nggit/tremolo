# Copyright (c) 2023 nggit

__all__ = ('Tremolo',)

import asyncio
import ipaddress
import logging
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

from .lib.connection_pool import ConnectionPool
from .lib.tremolo_protocol import TremoloProtocol

class Tremolo(TremoloProtocol):
    def __init__(self, *args, **kwargs):
        try:
            self._route_handlers = kwargs['_handlers']
            self._middlewares = kwargs['_middlewares']
            self._server = {
                'loop': kwargs['loop'],
                'logger': kwargs['logger'],
                'request': None,
                'response': None
            }

            super().__init__(*args, **kwargs)
        except KeyError:
            server = Server()

            for attr in dir(server):
                if not attr.startswith('__'):
                    setattr(self, attr, getattr(server, attr))

    def _set_base_header(self, options={}):
        if self._server['response'].header[1] != b'':
            return

        options['server_name'] = options.get('server_name', self.options['server_name'])

        if isinstance(options['server_name'], str):
            options['server_name'] = options['server_name'].encode(encoding='latin-1')

        self._server['response'].append_header(b'Date: %s\r\nServer: %s\r\n' % (
                                               datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT').encode(encoding='latin-1'),
                                               options['server_name']))

    async def _handle_middleware(self, func, options={}):
        self._set_base_header(options)

        data = await func(**{'options': options, **self._server})

        if data is None:
            return options

        if 'status' in options:
            self._server['response'].set_status(*options['status'])

        if 'content_type' in options:
            self._server['response'].set_content_type(options['content_type'])

        encoding = ('utf-8',)

        if isinstance(data, tuple):
            data, *encoding = (*data, 'utf-8')

        if isinstance(data, str):
            data = data.encode(encoding=encoding[0])

        await self._server['response'].end(data)

    async def _handle_response(self, func, options={}):
        options['rate'] = options.get('rate', self.options['download_rate'])
        options['buffer_size'] = options.get('buffer_size', self.options['buffer_size'])

        if 'status' in options:
            self._server['response'].set_status(*options['status'])

        if 'content_type' in options:
            self._server['response'].set_content_type(options['content_type'])

        self._set_base_header(options)

        agen = func(**{'options': options, **self._server})

        try:
            data = await agen.__anext__()
            is_agen = True
        except AttributeError:
            data = await agen

            if data is None:
                self._server['response'].close()
                return

            is_agen = False

        status = self._server['response'].get_status()
        no_content = status[0] in (204, 304) or 100 <= status[0] < 200
        self._server['response'].http_chunked = options.get(
            'chunked', self._server['request'].version == b'1.1' and self._server['request'].http_keepalive and not no_content
        )

        if self._server['response'].http_chunked:
            self._server['response'].append_header(b'Transfer-Encoding: chunked\r\n')

        if self._middlewares['data'][-1][0] is not None:
            self._server['response'].set_write_callback(
                lambda **kwargs : self._handle_middleware(self._middlewares['data'][-1][0], {**self._middlewares['data'][-1][1], **kwargs})
            )

        self._server['response'].header = b'HTTP/%s %d %s\r\n' % (self._server['request'].version, *status)

        if is_agen:
            if no_content:
                self._server['response'].append_header(b'Connection: close\r\n\r\n')
            else:
                if not self._server['response'].http_chunked:
                    self._server['request'].http_keepalive = False

                self._server['response'].append_header(b'Content-Type: %s\r\nConnection: keep-alive\r\n\r\n' %
                                                       self._server['response'].get_content_type())

            if not (self._server['request'].method == b'HEAD' or no_content):
                self.transport.set_write_buffer_limits(high=options['buffer_size'] * 4, low=options['buffer_size'] // 2)
                await self._server['response'].write(
                    data, rate=options['rate'], buffer_size=options['buffer_size']
                )

                while True:
                    try:
                        data = await agen.__anext__()

                        await self._server['response'].write(
                            data, rate=options['rate'], buffer_size=options['buffer_size']
                        )
                    except StopAsyncIteration:
                        await self._server['response'].write(b'', throttle=False)
                        break
        else:
            encoding = ('utf-8',)

            if isinstance(data, tuple):
                data, *encoding = (*data, 'utf-8')

            if isinstance(data, str):
                data = data.encode(encoding=encoding[0])

            if no_content or data == b'':
                self._server['response'].append_header(b'Connection: close\r\n\r\n')
            else:
                if self._server['response'].http_chunked:
                    self._server['response'].append_header(b'Content-Type: %s\r\nConnection: keep-alive\r\n\r\n'
                                                           % self._server['response'].get_content_type())
                else:
                    self._server['response'].append_header(
                        b'Content-Type: %s\r\nContent-Length: %d\r\nConnection: %s\r\n\r\n' % (
                        self._server['response'].get_content_type(), len(data), {
                            True: b'keep-alive',
                            False: b'close'}[self._server['request'].http_keepalive])
                    )

            if data != b'' and not (self._server['request'].method == b'HEAD' or no_content):
                self.transport.set_write_buffer_limits(high=options['buffer_size'] * 4, low=options['buffer_size'] // 2)
                await self._server['response'].write(data, rate=options['rate'], buffer_size=options['buffer_size'])
                await self._server['response'].write(b'', throttle=False)

        await self._server['response'].send(None)

    async def body_received(self, request, response):
        if request.content_type.find(b'application/x-www-form-urlencoded') > -1:
            async for data in request.read():
                request.append_body(data)

                if request.body_size > 8 * 1048576:
                    break

            if request.body_size <= 8 * 1048576:
                request.params['post'] = parse_qs((await request.body()).decode(encoding='latin-1'))

    async def header_received(self, request, response):
        self._server['request'] = request
        self._server['response'] = response
        options = {}

        for middleware in self._middlewares['request']:
            options = await self._handle_middleware(middleware[0], {**middleware[1], **options})

            if not isinstance(options, dict):
                return

        if request.is_valid:
            if b'cookie' in request.headers:
                if isinstance(request.headers[b'cookie'], list):
                    self._server['request'].cookies = parse_qs(
                        b'; '.join(request.headers[b'cookie']).replace(b'; ', b'&').replace(b';', b'&').decode(encoding='latin-1')
                    )
                else:
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
                ri = 1
            else:
                ri = b'%d#%s' % (p.count(b'/') + 2, p[:(p + b'/').find(b'/')])

            if ri in self._route_handlers:
                for (pattern, func, kwargs) in self._route_handlers[ri]:
                    m = pattern.search(request.path)

                    if m:
                        matches = m.groupdict()

                        if not matches:
                            matches = m.groups()

                        self._server['request'].params['url'] = matches

                        await self._handle_response(func, {**kwargs, **options})
                        return
            else:
                for i, (pattern, func, kwargs) in enumerate(self._route_handlers[-1]):
                    m = pattern.search(request.path)

                    if m:
                        if ri in self._route_handlers:
                            self._route_handlers[ri].append((pattern, func, kwargs))
                        else:
                            self._route_handlers[ri] = [(pattern, func, kwargs)]

                        matches = m.groupdict()

                        if not matches:
                            matches = m.groups()

                        self._server['request'].params['url'] = matches

                        await self._handle_response(func, {**kwargs, **options})
                        del self._route_handlers[-1][i]
                        return

            # not found
            await self._handle_response(self._route_handlers[0][1][1], {**self._route_handlers[0][1][2], **options})
        else:
            # bad request
            await self._handle_response(self._route_handlers[0][0][1], {**self._route_handlers[0][0][2], **options})

class Server():
    def __init__(self):
        self._listeners = []

        self._route_handlers = {
            0: [
                (None, self._err_badrequest, dict(status=(400, b'Bad Request'))),
                (None, self._err_notfound, dict(status=(404, b'Not Found')))
            ],
            1: [
                (b'^/+(?:\\?.*)?$', self._index, {})
            ],
            -1: []
        }

        self._middlewares = {
            'data': [
                (None, {})
            ],
            'request': []
        }

    def add_listener(self, port, host=None, **options):
        self._listeners.append((host, port, options))

    def route(self, path):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self._add_handler(path, wrapper, self._getoptions(func))
            return wrapper

        return decorator

    def errorhandler(self, status):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            for i, h in enumerate(self._route_handlers[0]):
                if status == h[2]['status'][0]:
                    self._route_handlers[0][i] = (None, wrapper, dict(h[2], **self._getoptions(func)))
                    break
            return wrapper

        return decorator

    def middleware(self, name):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self._middlewares[name].append((wrapper, self._getoptions(func)))
            return wrapper

        return decorator

    def on_data(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('data')(args[0])

        return self.middleware('data')

    def on_request(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('request')(args[0])

        return self.middleware('request')

    def _getoptions(self, func):
        options = {}

        if func.__defaults__ is not None:
            options = dict(zip(
                func.__code__.co_varnames[:len(func.__defaults__)],
                func.__defaults__
            ))

        return options

    def _add_handler(self, path='/', func=None, kwargs={}):
        if path.startswith('^') or path.endswith('$'):
            pattern = path.encode(encoding='latin-1')
            self._route_handlers[-1].append((pattern, func, kwargs))
        else:
            qs_pos = path.find('?')

            if qs_pos > -1:
                path = path[:qs_pos]

            p = path.strip('/')

            if p == '':
                ri = 1
                pattern = self._route_handlers[1][0][0]
                self._route_handlers[ri] = [(pattern, func, kwargs)]
            else:
                ri = '{:d}#{:s}'.format(p.count('/') + 2, p[:(p + '/').find('/')]).encode(encoding='latin-1')
                pattern = r'^/+{:s}(?:/+)?(?:\?.*)?$'.format(p).encode(encoding='latin-1')

                if ri in self._route_handlers:
                    self._route_handlers[ri].append((pattern, func, kwargs))
                else:
                    self._route_handlers[ri] = [(pattern, func, kwargs)]

    def _compile_handlers(self, handlers={}):
        for ri in handlers:
            for i, h in enumerate(handlers[ri]):
                pattern, *handler = h

                if isinstance(pattern, bytes):
                    handlers[ri][i] = (re.compile(pattern), *handler)

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
            server['options']['server_name'])

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
            except Exception:
                options['conn'].send(False)
                sock = options['conn'].recv()
                sock.listen()

        server_name = options.get('server_name', b'Tremolo')

        if isinstance(server_name, str):
            server_name = server_name.encode(encoding='latin-1')

        if isinstance(host, str):
            host = host.encode(encoding='latin-1')

        pool = ConnectionPool(1024, self._logger)

        server = await self._loop.create_server(
            lambda : Tremolo(loop=self._loop,
                             logger=self._logger,
                             debug=options.get('debug', False),
                             download_rate=options.get('download_rate', 1048576),
                             upload_rate=options.get('upload_rate', 1048576),
                             buffer_size=options.get('buffer_size', 16 * 1024),
                             client_max_body_size=options.get('client_max_body_size', 2 * 1048576),
                             server_name=server_name,
                             _pool=pool,
                             _handlers=options['handlers'],
                             _middlewares=options['middlewares']), sock=sock)

        print(datetime.now().strftime('[%Y-%m-%d %H:%M:%S]'), end=' ')
        sys.stdout.flush()
        sys.stdout.buffer.write(b'%s (pid %d) is started at %s port %d' % (server_name, os.getpid(), host, port))
        print()

        process_num = 1

        # serve forever
        while True:
            try:
                # ping parent process
                options['conn'].send(None)

                for _ in range(2 * process_num):
                    await asyncio.sleep(1)

                    if options['conn'].poll():
                        break

                process_num = options['conn'].recv()
            except (BrokenPipeError, ConnectionResetError, EOFError):
                server.close()
                break

    def _worker(self, host, port, **kwargs):
        self._compile_handlers(kwargs['handlers'])

        self._logger = logging.getLogger(mp.current_process().name)
        self._logger.setLevel(getattr(logging, kwargs.get('log_level', 'DEBUG'), logging.DEBUG))

        handler = logging.StreamHandler()
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')

        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._serve(host, port, **kwargs))
        finally:
            self._loop.close()

    def run(self, host, port=0, reuse_port=True, worker_num=1, **kwargs):
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

                p = mp.Process(
                    target=self._worker, args=args, kwargs=dict(options,
                                                                conn=child_conn,
                                                                family=sock.family,
                                                                handlers=deepcopy(self._route_handlers),
                                                                middlewares=self._middlewares)
                    )

                p.start()
                child_pid = parent_conn.recv()

                if hasattr(sock, 'share'):
                    parent_conn.send(sock.share(child_pid))
                else:
                    parent_conn.send(sock.fileno())

                    if parent_conn.recv() is False:
                        parent_conn.send(sock)

                processes.append((parent_conn, p, args, options))

            sock.close()

        while True:
            for i, (parent_conn, p, args, options) in enumerate(processes):
                if not p.is_alive():
                    print('A worker process died. Restarting...')

                    parent_conn.close()
                    parent_conn, child_conn = mp.Pipe()
                    p = mp.Process(
                        target=self._worker, args=args, kwargs=dict(options,
                                                                    conn=child_conn,
                                                                    family=sock.family,
                                                                    handlers=deepcopy(self._route_handlers),
                                                                    middlewares=self._middlewares)
                        )

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
                        parent_conn.close()
                        p.terminate()

                        print('pid {:d} terminated'.format(p.pid))
                    return
