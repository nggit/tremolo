# Copyright (c) 2023 nggit

__all__ = ('Tremolo',)

import asyncio  # noqa: E402
import ipaddress  # noqa: E402
import logging  # noqa: E402
import multiprocessing as mp  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import socket  # noqa: E402
import ssl  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

from datetime import datetime  # noqa: E402
from functools import wraps  # noqa: E402
from importlib import import_module  # noqa: E402

from .lib.locks import ServerLock  # noqa: E402
from .lib.pools import QueuePool  # noqa: E402
from .exceptions import BadRequest  # noqa: E402


class Tremolo:
    def __init__(self):
        self._ports = {}

        self._route_handlers = {
            0: [
                (400, self.error_400, {}),
                (404, self.error_404, dict(status=(404, b'Not Found')))
            ],
            1: [
                (
                    b'^/+(?:\\?.*)?$',
                    self.index, dict(status=(503, b'Service Unavailable'))
                )
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

        self._events = {
            'request': self._middlewares,
            'worker': {
                'start': [
                    None
                ],
                'stop': [
                    None
                ]
            }
        }

        self._loop = None
        self._logger = None

    @property
    def handlers(self):
        return self._route_handlers

    @property
    def middlewares(self):
        return self._middlewares

    def listen(self, port, host=None, **options):
        if (host, port) in self._ports:
            return False

        self._ports[(host, port)] = options
        return (host, port) in self._ports

    def route(self, path):
        if isinstance(path, int):
            return self.error(path)

        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self._add_handler(path, wrapper, self.getoptions(func))
            return wrapper

        return decorator

    def error(self, code):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            for i, h in enumerate(self._route_handlers[0]):
                if code == h[0]:
                    self._route_handlers[0][i] = (
                        h[0], wrapper, dict(h[2], **self.getoptions(func))
                    )
                    break

            return wrapper

        return decorator

    def worker(self, name):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self._events['worker'][name].append(wrapper)
            return wrapper

        return decorator

    def on_start(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.worker('start')(args[0])

        return self.worker('start')

    def on_stop(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.worker('stop')(args[0])

        return self.worker('stop')

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
            pattern = path.encode('latin-1')
            self._route_handlers[-1].append((pattern, func, kwargs))
        else:
            _path = path.split('?', 1)[0].strip('/')

            if _path == '':
                key = 1
                pattern = self._route_handlers[1][0][0]
                self._route_handlers[key] = [(pattern, func, kwargs)]
            else:
                key = '{:d}#{:s}'.format(
                    _path.count('/') + 2, _path[:(_path + '/').find('/')]
                ).encode('latin-1')
                pattern = r'^/+{:s}(?:/+)?(?:\?.*)?$'.format(
                    _path
                ).encode('latin-1')

                if key in self._route_handlers:
                    self._route_handlers[key].append((pattern, func, kwargs))
                else:
                    self._route_handlers[key] = [(pattern, func, kwargs)]

    def compile_handlers(self, handlers={}):
        for key in handlers:
            for i, h in enumerate(handlers[key]):
                pattern, *handler = h

                if isinstance(pattern, bytes):
                    handlers[key][i] = (re.compile(pattern), *handler)

    async def index(self, **_):
        return b'Service Unavailable'

    async def error_400(self, **_):
        raise BadRequest

    async def error_404(self, **server):
        yield (
            b'<!DOCTYPE html><html lang="en"><head><meta name="viewport" '
            b'content="width=device-width, initial-scale=1.0" />'
            b'<title>404 Not Found</title>'
            b'<style>body { max-width: 600px; margin: 0 auto; padding: 1%; '
            b'font-family: sans-serif; }</style></head><body>'
        )
        yield (b'<h1>Not Found</h1><p>Unable to find handler for %s.</p><hr />'
               b'<address>%s</address></body></html>') % (
                  (server['request'].path
                   .replace(b'&', b'&amp;')
                   .replace(b'<', b'&lt;')
                   .replace(b'>', b'&gt;')
                   .replace(b'"', b'&quot;')),
                  server['context'].options['server_name'])

    async def _serve(self, host, port, **options):
        on_start = self._events['worker']['start'][-1]

        if on_start is not None:
            await on_start(loop=self._loop, logger=self._logger)

        options['conn'].send(os.getpid())
        backlog = options.get('backlog', 100)

        if hasattr(socket, 'fromshare'):
            sock = socket.fromshare(options['conn'].recv())
            sock.listen(backlog)
        else:
            fd = options['conn'].recv()

            try:
                sock = socket.fromfd(fd, options['sa_family'],
                                     socket.SOCK_STREAM)
                sock.listen(backlog)
                options['conn'].send(True)
            except Exception:
                options['conn'].send(False)
                sock = options['conn'].recv()
                sock.listen(backlog)

        if ('ssl' in options and options['ssl'] and
                isinstance(options['ssl'], dict)):
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(
                certfile=options['ssl'].get('cert', ''),
                keyfile=options['ssl'].get('key'),
                password=options['ssl'].get('password')
            )
        else:
            ssl_context = None

        server_name = options.get('server_name', b'Tremolo')

        if isinstance(server_name, str):
            server_name = server_name.encode('latin-1')

        if isinstance(host, str):
            host = host.encode('latin-1')

        lock = ServerLock(options['locks'], loop=self._loop)
        pools = {
            'queue': QueuePool(1024, self._logger)
        }
        lifespan = None

        if 'app' in options and isinstance(options['app'], str):
            from .asgi_lifespan import ASGILifespan
            from .asgi_server import ASGIServer as Server

            # 'module:app'               -> 'module:app'   (dir: os.getcwd())
            # '/path/to/module.py'       -> 'module:app'   (dir: '/path/to')
            # '/path/to/module.py:myapp' -> 'module:myapp' (dir: '/path/to')

            if (':\\' in options['app'] and options['app'].count(':') < 2 or
                    ':' not in options['app']):
                options['app'] += ':app'

            path, attr_name = options['app'].rsplit(':', 1)
            dir_name, base_name = os.path.split(path)
            module_name = os.path.splitext(base_name)[0]

            if dir_name == '':
                dir_name = os.getcwd()

            sys.path.insert(0, dir_name)

            options['app'] = getattr(import_module(module_name), attr_name)

            print(datetime.now().strftime('[%Y-%m-%d %H:%M:%S]'), end=' ')
            sys.stdout.flush()
            sys.stdout.buffer.write(
                b'Starting %s as an ASGI server for: ' % server_name
            )
            print(
                getattr(options['app'], '__name__',
                        options['app'].__class__.__name__)
            )

            if server_name != b'':
                server_name = server_name + b' (ASGI)'

            lifespan = ASGILifespan(options['app'],
                                    loop=self._loop, logger=self._logger)

            lifespan.startup()
            exc = await lifespan.exception()

            if exc:
                raise exc
        else:
            from .http_server import HTTPServer as Server

            options['app'] = None
            self.compile_handlers(options['handlers'])

        server = await self._loop.create_server(
            lambda: Server(loop=self._loop,
                           logger=self._logger,
                           lock=lock,
                           sock=sock,
                           debug=options.get('debug', False),
                           download_rate=options.get('download_rate', 1048576),
                           upload_rate=options.get('upload_rate', 1048576),
                           buffer_size=options.get('buffer_size', 16 * 1024),
                           client_max_body_size=options.get(
                               'client_max_body_size', 2 * 1048576
                           ),
                           request_timeout=options.get('request_timeout', 30),
                           keepalive_timeout=options.get(
                               'keepalive_timeout', 30
                           ),
                           server_name=server_name,
                           _pools=pools,
                           _app=options['app'],
                           _root_path=options.get('root_path', ''),
                           _handlers=options['handlers'],
                           _middlewares=options['middlewares']),
            sock=sock, backlog=backlog, ssl=ssl_context)

        print(datetime.now().strftime('[%Y-%m-%d %H:%M:%S]'), end=' ')
        sys.stdout.flush()
        sys.stdout.buffer.write(
            b'%s (pid %d) is started at %s port %d' % (
                server_name, os.getpid(), host, port)
        )

        if ssl_context is not None:
            sys.stdout.buffer.write(b' (https)')

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
                break

        server.close()

        if lifespan is not None:
            lifespan.shutdown()
            await lifespan.exception()

        on_stop = self._events['worker']['stop'][-1]

        if on_stop is not None:
            await on_stop(loop=self._loop, logger=self._logger)

    def _worker(self, host, port, **kwargs):
        self._logger = logging.getLogger(mp.current_process().name)
        self._logger.setLevel(
            getattr(logging, kwargs.get('log_level', 'DEBUG'), logging.DEBUG)
        )

        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s'
        )

        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._serve(host, port, **kwargs))
        except KeyboardInterrupt:
            pass
        finally:
            self._loop.close()

    def create_sock(self, host, port, reuse_port=True):
        try:
            sock = socket.socket({
                4: socket.AF_INET,
                6: socket.AF_INET6
            }[ipaddress.ip_address(host).version], socket.SOCK_STREAM)
        except ValueError:
            sock = socket.socket(type=socket.SOCK_STREAM)

        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, {
            True: getattr(socket, 'SO_REUSEPORT', socket.SO_REUSEADDR),
            False: socket.SO_REUSEADDR
        }[reuse_port], 1)
        sock.setblocking(False)
        sock.bind((host, port))
        sock.set_inheritable(True)

        return sock

    def run(self, host=None, port=80, reuse_port=True, worker_num=1, **kwargs):
        if 'app' in kwargs:
            if not isinstance(kwargs['app'], str):
                import __main__

                if hasattr(__main__, '__file__'):
                    for attr_name in dir(__main__):
                        if attr_name.startswith('__'):
                            continue

                        if getattr(__main__, attr_name) == kwargs['app']:
                            break
                    else:
                        attr_name = 'app'

                    kwargs['app'] = '{:s}:{:s}'.format(__main__.__file__,
                                                       attr_name)

            locks = []
        else:
            locks = [mp.Lock() for _ in range(kwargs.get('locks', 16))]

        if host is None:
            host = ''
        else:
            self.listen(port, host=host, **kwargs)

        try:
            worker_num = min(worker_num, len(os.sched_getaffinity(0)))
        except AttributeError:
            worker_num = min(worker_num, os.cpu_count() or 1)

        processes = []
        socks = {}

        for (_host, _port), options in self._ports.items():
            if _host is None:
                _host = host

            args = (_host, _port)
            socks[args] = self.create_sock(
                _host, _port, options.get('reuse_port', reuse_port)
            )

            for _ in range(options.get('worker_num', worker_num)):
                parent_conn, child_conn = mp.Pipe()

                p = mp.Process(
                    target=self._worker,
                    args=args,
                    kwargs=dict(options,
                                locks=locks,
                                conn=child_conn,
                                sa_family=socks[args].family,
                                handlers=self._route_handlers,
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
                            target=self._worker,
                            args=args,
                            kwargs=dict(options,
                                        locks=locks,
                                        conn=child_conn,
                                        sa_family=socks[args].family,
                                        handlers=self._route_handlers,
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
            p.join()

            print('pid {:d} terminated'.format(p.pid))

        for sock in socks.values():
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
