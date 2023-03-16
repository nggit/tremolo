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

from .lib.connection_pool import ConnectionPool
from .http_server import HTTPServer

class Tremolo:
    def __init__(self):
        self._ports = []

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
            'connect': [
                (None, {})
            ],
            'send': [
                (None, {})
            ],
            'close': [
                (None, {})
            ],
            'request': []
        }

    def listen(self, port, host=None, **options):
        self._ports.append((host, port, options))

    def route(self, path):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self._add_handler(path, wrapper, self.getoptions(func))
            return wrapper

        return decorator

    def errorhandler(self, status):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            for i, h in enumerate(self._route_handlers[0]):
                if status == h[2]['status'][0]:
                    self._route_handlers[0][i] = (None, wrapper, dict(h[2], **self.getoptions(func)))
                    break
            return wrapper

        return decorator

    def middleware(self, name):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self._middlewares[name].append((wrapper, self.getoptions(func)))
            return wrapper

        return decorator

    def on_connect(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('connect')(args[0])

        return self.middleware('connect')

    def on_send(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('send')(args[0])

        return self.middleware('send')

    def on_close(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('close')(args[0])

        return self.middleware('close')

    def on_request(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('request')(args[0])

        return self.middleware('request')

    def getoptions(self, func):
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
            server['context'].options['server_name'])

    async def _serve(self, host, port, **options):
        options['conn'].send(os.getpid())

        if hasattr(socket, 'fromshare'):
            sock = socket.fromshare(options['conn'].recv())
            sock.listen()
        else:
            fd = options['conn'].recv()

            try:
                sock = socket.fromfd(fd, options['sa_family'], socket.SOCK_STREAM)
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
            lambda : HTTPServer(loop=self._loop,
                                logger=self._logger,
                                sock=sock,
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

    def _create_sock(self, host, port, reuse_port):
        try:
            sock = socket.socket({4: socket.AF_INET,
                                  6: socket.AF_INET6
                                  }[ipaddress.ip_address(host).version], socket.SOCK_STREAM)
        except ValueError:
            sock = socket.socket(type=socket.SOCK_STREAM)

        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, {True: getattr(socket, 'SO_REUSEPORT', socket.SO_REUSEADDR),
                                            False: socket.SO_REUSEADDR
                                            }[reuse_port], 1)
        sock.bind((host, port))
        sock.set_inheritable(True)

        return sock

    def run(self, host, port=0, reuse_port=True, worker_num=1, **kwargs):
        default_host = host
        self.listen(port, host=host, **kwargs)

        try:
            worker_num = min(worker_num, len(os.sched_getaffinity(0)))
        except AttributeError:
            worker_num = min(worker_num, os.cpu_count() or 1)

        processes = []
        socks = {}

        for host, port, options in self._ports:
            if host is None:
                host = default_host

            args = (host, port)
            socks[args] = self._create_sock(host, port, options.get('reuse_port', reuse_port))

            for _ in range(options.get('worker_num', worker_num)):
                parent_conn, child_conn = mp.Pipe()

                p = mp.Process(
                    target=self._worker, args=args, kwargs=dict(options,
                                                                conn=child_conn,
                                                                sa_family=socks[args].family,
                                                                handlers=deepcopy(self._route_handlers),
                                                                middlewares=self._middlewares)
                    )

                p.start()
                child_pid = parent_conn.recv()

                if hasattr(socks[args], 'share'):
                    parent_conn.send(socks[args].share(child_pid))
                else:
                    parent_conn.send(socks[args].fileno())

                    if parent_conn.recv() is False:
                        parent_conn.send(socks[args])

                processes.append((parent_conn, p, args, options))

        while True:
            try:
                for i, (parent_conn, p, args, options) in enumerate(processes):
                    if not p.is_alive():
                        print('A worker process died. Restarting...')

                        parent_conn.close()
                        parent_conn, child_conn = mp.Pipe()
                        p = mp.Process(
                            target=self._worker, args=args, kwargs=dict(options,
                                                                        conn=child_conn,
                                                                        sa_family=socks[args].family,
                                                                        handlers=deepcopy(self._route_handlers),
                                                                        middlewares=self._middlewares)
                            )

                        p.start()
                        pid = parent_conn.recv()

                        if hasattr(socks[args], 'share'):
                            parent_conn.send(socks[args].share(pid))
                        else:
                            parent_conn.send(socks[args].fileno())

                            if parent_conn.recv() is False:
                                parent_conn.send(socks[args])

                        processes[i] = (parent_conn, p, args, options)

                    # response ping from child
                    while parent_conn.poll():
                        parent_conn.recv()
                        parent_conn.send(len(processes))

                    time.sleep(1)
            except KeyboardInterrupt:
                break

        for parent_conn, p, *_ in processes:
            parent_conn.close()
            p.terminate()

            print('pid {:d} terminated'.format(p.pid))

        for sock in socks.values():
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
