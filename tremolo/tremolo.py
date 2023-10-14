# Copyright (c) 2023 nggit

__all__ = ('Tremolo',)

import asyncio  # noqa: E402
import logging  # noqa: E402
import multiprocessing as mp  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import socket  # noqa: E402
import ssl  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

from functools import wraps  # noqa: E402
from importlib import import_module  # noqa: E402

from . import handlers  # noqa: E402
from .utils import log_date, server_date  # noqa: E402
from .lib.connections import KeepAliveConnections  # noqa: E402
from .lib.contexts import ServerContext as WorkerContext  # noqa: E402
from .lib.locks import ServerLock  # noqa: E402
from .lib.pools import QueuePool  # noqa: E402

_REUSEPORT_OR_REUSEADDR = {
    True: getattr(socket, 'SO_REUSEPORT', socket.SO_REUSEADDR),
    False: socket.SO_REUSEADDR
}


class Tremolo:
    def __init__(self):
        self._ports = {}

        self.routes = {
            0: [
                (400, handlers.error_400, {}),
                (404, handlers.error_404, dict(status=(404, b'Not Found'),
                                               stream=False))
            ],
            1: [
                (
                    b'^/+(?:\\?.*)?$',
                    handlers.index, dict(status=(503, b'Service Unavailable'))
                )
            ],
            -1: []
        }

        self.middlewares = {
            'connect': [],
            'close': [],
            'request': [],
            'response': []
        }

        self.events = {
            'worker_start': [],
            'worker_stop': []
        }

        self._loop = None
        self._logger = None

    def listen(self, port, host=None, **options):
        if not isinstance(port, int):
            # assume it's a UNIX socket path
            host = port
            port = None

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

            self.add_route(path, wrapper, self.getoptions(func))
            return wrapper

        return decorator

    def error(self, code):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            for i, h in enumerate(self.routes[0]):
                if code == h[0]:
                    self.routes[0][i] = (
                        h[0], wrapper, dict(h[2], **self.getoptions(func))
                    )
                    break

            return wrapper

        return decorator

    def event(self, name):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self.events[name].append(wrapper)
            return wrapper

        return decorator

    def on_worker_start(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.event('worker_start')(args[0])

        return self.event('worker_start')

    def on_worker_stop(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.event('worker_stop')(args[0])

        return self.event('worker_stop')

    def middleware(self, name):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self.middlewares[name].append((wrapper, self.getoptions(func)))
            return wrapper

        return decorator

    def on_connect(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('connect')(args[0])

        return self.middleware('connect')

    def on_close(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('close')(args[0])

        return self.middleware('close')

    def on_request(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('request')(args[0])

        return self.middleware('request')

    def on_response(self, *args):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('response')(args[0])

        return self.middleware('response')

    def getoptions(self, func):
        options = {}

        if func.__defaults__ is not None:
            options = dict(zip(
                func.__code__.co_varnames[:len(func.__defaults__)],
                func.__defaults__
            ))

        return options

    def add_route(self, path, func, kwargs={}):
        if path.startswith('^') or path.endswith('$'):
            pattern = path.encode('latin-1')
            self.routes[-1].append((pattern, func, kwargs))
        else:
            _path = path.split('?', 1)[0].strip('/')

            if _path == '':
                key = 1
                pattern = self.routes[1][0][0]
                self.routes[key] = [(pattern, func, kwargs)]
            else:
                key = '{:d}#{:s}'.format(
                    _path.count('/') + 2, _path[:(_path + '/').find('/')]
                ).encode('latin-1')
                pattern = r'^/+{:s}(?:/+)?(?:\?.*)?$'.format(
                    _path
                ).encode('latin-1')

                if key in self.routes:
                    self.routes[key].append((pattern, func, kwargs))
                else:
                    self.routes[key] = [(pattern, func, kwargs)]

    def compile_routes(self, routes={}):
        for key in routes:
            for i, h in enumerate(routes[key]):
                pattern, *handler = h

                if isinstance(pattern, bytes):
                    routes[key][i] = (re.compile(pattern), *handler)

    async def _serve(self, host, port, **options):
        context = WorkerContext()

        for func in self.events['worker_start']:
            if (await func(context=context,
                           loop=self._loop,
                           logger=self._logger)):
                break

        options['_conn'].send(os.getpid())
        backlog = options.get('backlog', 100)

        if hasattr(socket, 'fromshare'):
            # Windows
            sock = socket.fromshare(options['_conn'].recv())
            sock.listen(backlog)
        else:
            fd = options['_conn'].recv()

            try:
                # Linux 'fork'
                sock = socket.fromfd(fd, options['_sa_family'],
                                     socket.SOCK_STREAM)
                sock.listen(backlog)
                options['_conn'].send(True)
            except OSError:
                # Linux 'spawn'
                options['_conn'].send(False)
                sock = options['_conn'].recv()
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

        lock = ServerLock(options['_locks'], loop=self._loop)
        connections = KeepAliveConnections(
            maxlen=options.get('keepalive_connections', 512)
        )
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

            print(log_date(), end=' ')
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
            self.compile_routes(options['_routes'])

        server_info = {
            'date': server_date(),
            'name': server_name
        }
        server = await self._loop.create_server(
            lambda: Server(loop=self._loop,
                           logger=self._logger,
                           lock=lock,
                           worker=context,
                           debug=options.get('debug', False),
                           ws=options.get('ws', True),
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
                           server_info=server_info,
                           _connections=connections,
                           _pools=pools,
                           _app=options['app'],
                           _root_path=options.get('root_path', ''),
                           _routes=options['_routes'],
                           _middlewares=options['_middlewares']),
            sock=sock, backlog=backlog, ssl=ssl_context)

        print(log_date(), end=' ')
        sys.stdout.flush()
        sys.stdout.buffer.write(
            b'%s (pid %d) is started at ' % (server_name, os.getpid())
        )

        if sock.family.name == 'AF_UNIX':
            print(sock.getsockname(), end='')
        else:
            print('%s port %d' % sock.getsockname()[:2], end='')

        if ssl_context is not None:
            sys.stdout.flush()
            sys.stdout.buffer.write(b' (https)')

        print()

        process_num = 1

        # serve forever
        while True:
            try:
                # ping parent process
                options['_conn'].send(None)

                for _ in range(2 * process_num):
                    await asyncio.sleep(1)

                    # update server date
                    server_info['date'] = server_date()

                    if options['_conn'].poll():
                        break

                process_num = options['_conn'].recv()
            except (BrokenPipeError, ConnectionResetError, EOFError):
                break

        server.close()

        if lifespan is not None:
            lifespan.shutdown()
            await lifespan.exception()

        i = len(self.events['worker_stop'])

        while i > 0:
            i -= 1

            if (await self.events['worker_stop'][i](
                    context=context,
                    loop=self._loop,
                    logger=self._logger)):
                break

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
            try:
                socket.getaddrinfo(host, None)

                if ':' in host:
                    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)

                    if host == '::' and hasattr(socket, 'IPPROTO_IPV6'):
                        sock.setsockopt(socket.IPPROTO_IPV6,
                                        socket.IPV6_V6ONLY, 0)
                else:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            except socket.gaierror:
                _host = host
                host = 'localhost'
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                host = _host
        except AttributeError:
            print('either AF_INET6 or AF_UNIX is not supported')
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        sock.setblocking(False)
        sock.set_inheritable(True)

        if sock.family.name == 'AF_UNIX':
            if not host.endswith('.sock'):
                host += '.sock'

            for _ in range(2):
                try:
                    sock.bind(host)
                    break
                except OSError:
                    if os.path.exists(host) and os.stat(host).st_size == 0:
                        os.unlink(host)
        else:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET,
                            _REUSEPORT_OR_REUSEADDR[reuse_port], 1)
            sock.bind((host, port))

        return sock

    def run(self, host=None, port=0, reuse_port=True, worker_num=1, **kwargs):
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
            if not self._ports:
                raise ValueError(
                    'with host=None, listen() must be called first'
                )

            host = 'localhost'
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

            if _port is None:
                _port = port

            options = {**kwargs, **options}

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
                                _locks=locks,
                                _conn=child_conn,
                                _sa_family=socks[args].family,
                                _routes=self.routes,
                                _middlewares=self.middlewares)
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
                                        _locks=locks,
                                        _conn=child_conn,
                                        _sa_family=socks[args].family,
                                        _routes=self.routes,
                                        _middlewares=self.middlewares)
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
            try:
                if sock.family.name == 'AF_UNIX':
                    os.unlink(sock.getsockname())
            except (FileNotFoundError, ValueError):
                pass

            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
