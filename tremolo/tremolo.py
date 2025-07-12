# Copyright (c) 2023 nggit

__all__ = ('Tremolo',)

import asyncio  # noqa: E402
import logging  # noqa: E402
import multiprocessing as mp  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import ssl  # noqa: E402
import sys  # noqa: E402

from importlib import import_module, reload as reload_module  # noqa: E402
from shutil import get_terminal_size  # noqa: E402

from . import __version__  # noqa: E402
from .managers import ProcessManager  # noqa: E402
from .routes import Routes  # noqa: E402
from .utils import (  # noqa: E402
    file_signature, getoptions, log_date, memory_usage, print_logo, server_date
)
from .lib.connections import KeepAliveConnections  # noqa: E402
from .lib.contexts import WorkerContext  # noqa: E402
from .lib.executors import MultiThreadExecutor  # noqa: E402
from .lib.locks import ServerLock  # noqa: E402


class Tremolo:
    def __init__(self, name=None):
        self.logger = None if name is None else logging.getLogger(name)
        self.context = WorkerContext()
        self.manager = ProcessManager()
        self.routes = Routes()
        self.middlewares = {
            (): {
                'request': [],
                'response': []
            }
        }
        self.hooks = {
            'worker_start': [],
            'worker_stop': [],
            'connect': [],
            'close': []
        }
        self.ports = {}

    @property
    def loop(self):
        return asyncio.get_event_loop()

    def create_task(self, coro):
        task = self.loop.create_task(coro)

        self.context.tasks.add(task)
        task.add_done_callback(self.context.tasks.discard)

        return task

    def route(self, path, **options):
        if isinstance(path, int):
            return self.error(path)

        def decorator(func):
            self.add_route(func, path, **options)
            return func

        return decorator

    def error(self, code):
        def decorator(func):
            for i, h in enumerate(self.routes[0]):
                if code == h[0]:
                    self.routes[0][i] = (
                        h[0], func, dict(h[2], **getoptions(func)), h[3]
                    )
                    break

            return func

        return decorator

    def hook(self, name, *args, priority=999):
        def decorator(func):
            self.add_hook(func, name, priority)
            return func

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])

        return decorator

    def on_worker_start(self, *args, **kwargs):
        return self.hook('worker_start', *args, **kwargs)

    def on_worker_stop(self, *args, **kwargs):
        return self.hook('worker_stop', *args, **kwargs)

    def on_connect(self, *args, **kwargs):
        return self.hook('connect', *args, **kwargs)

    def on_close(self, *args, **kwargs):
        return self.hook('close', *args, **kwargs)

    def middleware(self, name, *args, priority=999):
        def decorator(func):
            self.add_middleware(func, name, priority, kwargs=getoptions(func))
            return func

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])

        return decorator

    def on_request(self, *args, **kwargs):
        return self.middleware('request', *args, **kwargs)

    def on_response(self, *args, **kwargs):
        return self.middleware('response', *args, **kwargs)

    def add_route(self, func, path='/', **options):
        if isinstance(func, type):  # a class-based view
            for name in dir(func):
                if name.startswith('_'):
                    continue

                method = getattr(func, name)

                if callable(method):
                    self.routes.add(
                        method, path, dict(getoptions(method), self=func),
                        **options
                    )
        else:
            self.routes.add(func, path, getoptions(func))

    def add_hook(self, func, name='worker_start', priority=999):
        if name not in self.hooks:
            raise ValueError('%s is not one of the: %s' %
                             (name, ', '.join(self.hooks)))

        self.hooks[name].append((priority, func))
        self.hooks[name].sort(key=lambda item: item[0],
                              reverse=name in ('worker_stop', 'close'))

    def add_middleware(self, func, name='request', priority=999, *,
                       kwargs=None, prefix=()):
        if name not in self.middlewares[()]:
            raise ValueError('%s is not one of the: %s' %
                             (name, ', '.join(self.middlewares[()])))

        if prefix not in self.middlewares:
            self.middlewares[prefix] = {
                'request': [],
                'response': []
            }

        self.middlewares[prefix][name].append(
            (priority, func, kwargs or getoptions(func))
        )
        self.middlewares[prefix][name].sort(key=lambda item: item[0],
                                            reverse=name == 'response')

    def listen(self, port, host=None, **options):
        if not isinstance(port, int):
            # assume it's a UNIX socket path
            host = port
            port = None

        if (host, port) in self.ports:
            return False

        self.ports[(host, port)] = options
        return (host, port) in self.ports

    def mount(self, prefix, app):
        if not prefix.startswith('/') or len(prefix) > 255:
            raise ValueError('prefix must start with "/" and <=255 in length')

        if app is self or not isinstance(app, self.__class__):
            raise ValueError('invalid app')

        prefix = prefix.rstrip('/').encode('latin-1')

        while app.routes:
            _, routes = app.routes.popitem()

            for pattern, func, kwargs, options in routes:
                if isinstance(pattern, bytes):
                    pattern = pattern.lstrip(b'^')

                    if pattern.startswith(b'/'):
                        pattern = b'^' + prefix + pattern
                    else:
                        pattern = b'^' + prefix + b'/.*' + pattern

                    self.routes[-1].append((pattern, func, kwargs, options))

        parts = tuple(part for part in prefix.split(b'/') if part)

        while app.middlewares:
            p, middlewares = app.middlewares.popitem()

            for name in middlewares:
                for middleware in middlewares[name]:
                    self.add_middleware(middleware[1], name, middleware[0],
                                        kwargs=middleware[2], prefix=parts + p)

        while app.hooks:
            name, hooks = app.hooks.popitem()

            for priority, func in hooks:
                self.add_hook(func, name, priority)

        while app.ports:
            self.ports.setdefault(*app.ports.popitem())

    async def _serve(self, host, port, **kwargs):
        options = self.context.options
        options.update(kwargs)

        backlog = options.get('backlog', 100)
        sock = options['_sock'] or self.create_sock(host, port)
        sock.listen(backlog)

        if 'ssl' in options and isinstance(options['ssl'] or None, dict):
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

        executor = MultiThreadExecutor(size=options['thread_pool_size'])
        executor.start()

        lock = ServerLock(options['_locks'], executor, loop=self.loop)
        connections = KeepAliveConnections(
            maxlen=options.get('keepalive_connections', 512)
        )
        self.context.update(connections=connections, executor=executor)
        options['state'] = {}

        for _, func in self.hooks['worker_start']:
            try:
                coro = func(app=self,
                            globals=self.context,
                            context=self.context,
                            loop=self.loop,
                            logger=self.logger)
            except TypeError:
                coro = func(app=self)

            if await coro:
                break

        if options['app'] is None:
            from .http_server import HTTPServer as Server

            self.routes.compile(executor=executor)
        else:
            from .asgi_lifespan import ASGILifespan
            from .asgi_server import ASGIServer as Server

            # 'module:app'               -> 'module:app'   (dir: os.getcwd())
            # '/path/to/module.py'       -> 'module:app'   (dir: '/path/to')
            # '/path/to/module.py:myapp' -> 'module:myapp' (dir: '/path/to')

            if options['app'].find(':', options['app'].find(':\\') + 1) == -1:
                options['app'] += ':app'

            path, attr_name = options['app'].rsplit(':', 1)
            options['app_dir'], basename = os.path.split(os.path.abspath(path))
            module_name = os.path.splitext(basename)[0]

            if options['app_dir'] == '':
                options['app_dir'] = os.getcwd()

            sys.path.insert(0, options['app_dir'])
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

            if server_name == b'Tremolo':
                server_name += b' (ASGI)'

            self.context.lifespan = ASGILifespan(self, options=options)
            self.context.lifespan.startup()
            exc = await self.context.lifespan.exception(
                timeout=options['shutdown_timeout'] / 2
            )

            if exc:
                raise exc

        sockname = sock.getsockname()

        if isinstance(sockname, tuple):
            self.context.info['server'] = sockname[:2]
        else:
            self.context.info['server'] = (sockname, None)

        self.context.info['server_date'] = server_date()
        self.context.info['server_name'] = server_name

        options.setdefault('debug', False)
        options.setdefault('experimental', False)
        options.setdefault('ws', True)
        options.setdefault('ws_max_payload_size', 2 * 1048576)
        options.setdefault('download_rate', 1048576)
        options.setdefault('upload_rate', 1048576)
        options.setdefault('buffer_size', 16384)
        options.setdefault('client_max_body_size', 2 * 1048576)
        options.setdefault('client_max_header_size', 8192)
        options.setdefault('max_queue_size', 128)
        options.setdefault('request_timeout', 30)
        options.setdefault('keepalive_timeout', 30)
        options.setdefault('app_handler_timeout', 120)
        options.setdefault('app_close_timeout', 30)
        options.setdefault('root_path', '')

        server = await self.loop.create_server(
            lambda: Server(app=self, lock=lock, options=options),
            sock=sock, backlog=backlog, ssl=ssl_context
        )

        print(log_date(), end=' ')
        sys.stdout.flush()
        sys.stdout.buffer.write(
            b'%s worker (pid %d) is started at ' % (server_name, os.getpid())
        )
        print(self.context.info['server'][0], end='')

        if self.context.info['server'][1] is not None:
            print(' port %d' % self.context.info['server'][1], end='')

        if ssl_context is not None:
            sys.stdout.flush()
            sys.stdout.buffer.write(b' (https)')

        print()

        try:
            await self._serve_forever()
        except asyncio.CancelledError:
            self.logger.info('Shutting down')

            if self.context.tasks:
                _, pending = await asyncio.wait(
                    self.context.tasks, timeout=options['shutdown_timeout'] / 2
                )
                for task in pending:
                    task.cancel()
        finally:
            server.close()

            while self.context.tasks:
                await self.context.tasks.pop()

            await server.wait_closed()
            await self._worker_stop()
            await executor.shutdown()

    async def _serve_forever(self):
        limit_memory = self.context.options.get('limit_memory', 0)
        paths = [path for path in sys.path
                 if not self.context.options['app_dir'].startswith(path)]
        modules = {}

        while True:
            await asyncio.sleep(1)

            # update server date
            self.context.info['server_date'] = server_date()

            # detect code changes
            if self.context.options.get('reload', False):
                for module in (dict(modules) or sys.modules.values()):
                    module_file = getattr(module, '__file__', None)

                    if module_file is None:
                        continue

                    for path in paths:
                        if module_file.startswith(path):
                            break
                    else:
                        if not os.path.exists(module_file):
                            if module in modules:
                                del modules[module]

                            continue

                        sign = file_signature(module_file)

                        if module in modules:
                            if modules[module] == sign:
                                # file not modified
                                continue

                            modules[module] = sign
                        else:
                            modules[module] = sign
                            continue

                        self.logger.info('reload: %s', module_file)
                        sys.exit(3)

            if limit_memory > 0 and memory_usage() > limit_memory:
                while self.context.tasks:
                    self.context.tasks.pop().cancel()

                self.logger.error('memory limit exceeded')
                sys.exit(1)

    async def _worker_stop(self):
        try:
            if self.context.options['app'] is not None:
                self.context.lifespan.shutdown()
                exc = await self.context.lifespan.exception(
                    timeout=self.context.options['shutdown_timeout'] / 2
                )

                if exc:
                    self.logger.error(exc)
        finally:
            for _, func in reversed(self.hooks['worker_stop']):
                try:
                    coro = func(app=self,
                                globals=self.context,
                                context=self.context,
                                loop=self.loop,
                                logger=self.logger)
                except TypeError:
                    coro = func(app=self)

                if await coro:
                    break

    def _worker(self, host, port, **kwargs):
        if self.logger is None:
            self.logger = logging.getLogger(mp.current_process().name)

        self.logger.setLevel(
            getattr(logging, kwargs['log_level'], logging.DEBUG)
        )
        formatter = logging.Formatter(
            kwargs.get('log_fmt',
                       '[%(asctime)s] %(module)s: %(levelname)s: %(message)s')
        )
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        loop_name = kwargs.get('loop', 'asyncio.')

        if '.' not in loop_name:
            loop_name += '.'

        # 'asyncio', '.', ''
        # 'asyncio', '.', 'SelectorEventLoop'
        module_name, _, class_name = loop_name.rpartition('.')
        module = import_module(module_name or 'asyncio')
        loop = getattr(module, class_name or 'new_event_loop')()
        task = loop.create_task(self._serve(host, port, **kwargs))

        task.add_done_callback(lambda fut: loop.stop())
        signal.signal(signal.SIGINT, lambda signum, frame: task.cancel())
        signal.signal(signal.SIGTERM, lambda signum, frame: task.cancel())

        try:
            loop.run_forever()  # until loop.stop() is called
        except BaseException:
            while self.context.tasks:
                self.context.tasks.pop().cancel()

            task.cancel()

            if not task.done():
                loop.run_forever()

            raise
        finally:
            loop.close()

            if not task.cancelled():
                exc = task.exception()

                if exc:
                    raise exc

    def create_sock(self, host, port, reuse_port=True):
        try:
            try:
                socket.getaddrinfo(host, None)

                if ':' in host:
                    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)

                    if host == '::' and hasattr(socket, 'IPPROTO_IPV6'):
                        # on Windows, Python versions below 3.8
                        # don't properly support dual-stack IPv4/6.
                        # https://github.com/python/cpython/issues/73701
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
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            if reuse_port:
                sock.setsockopt(
                    socket.SOL_SOCKET,
                    getattr(socket, 'SO_REUSEPORT_LB', socket.SO_REUSEPORT),
                    1
                )

            sock.bind((host, port))

        return sock

    def close_sock(self, sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()

            if sock.family.name == 'AF_UNIX':
                os.unlink(sock.getsockname())
        except FileNotFoundError:
            pass
        except OSError:
            sock.close()

    def _handle_reload(self, **info):
        args = info['args']
        kwargs = info['kwargs']
        process = info['process']

        if process.exitcode == 3:
            print('Reloading...')

            if kwargs['app'] is None:
                for module in list(sys.modules.values()):
                    module_file = getattr(module, '__file__', None)

                    if (module_file and
                            module.__name__ not in ('__main__',
                                                    '__mp_main__',
                                                    'tremolo') and
                            not module.__name__.startswith('tremolo.') and
                            module_file.startswith(kwargs['app_dir']) and
                            os.path.exists(module_file)):
                        reload_module(module)

                module = import_module(kwargs['module_name'])

                # we need to update/rebind objects like
                # routes, middlewares, etc.
                for attr in module.__dict__.values():
                    if isinstance(attr, self.__class__) and attr.routes:
                        self.__dict__.update(attr.__dict__)
        elif process.exitcode != 0:
            print(
                'A worker process died (%d). Restarting...' % process.exitcode
            )

        if process.exitcode == 0:
            print('pid %d terminated' % process.pid)
        else:
            self.manager.spawn(
                self._worker, args=args, kwargs=kwargs,
                name=process.name,
                exit_cb=self._handle_reload
            )

    def run(self, host=None, port=0, *, worker_num=1, **kwargs):
        kwargs['log_level'] = kwargs.get('log_level', 'DEBUG').upper()
        kwargs.setdefault('thread_pool_size', 5)
        kwargs.setdefault('shutdown_timeout', 30)
        server_name = kwargs.get('server_name', 'Tremolo')
        terminal_width = min(get_terminal_size()[0], 72)

        if server_name == 'Tremolo' and terminal_width > 44:
            print_logo()

        print(
            'Starting %s (tremolo %s, %s %d.%d.%d, %s)' %
            (server_name,
             __version__,
             sys.implementation.name,
             *sys.version_info[:3],
             sys.platform)
        )
        print('-' * terminal_width)

        import __main__

        if 'app' in kwargs and kwargs['app']:
            if not isinstance(kwargs['app'], str):
                if not hasattr(__main__, '__file__'):
                    raise RuntimeError('could not find ASGI app')

                for attr_name, attr in __main__.__dict__.items():
                    if attr == kwargs['app']:
                        break
                else:
                    attr_name = 'app'

                kwargs['app'] = '%s:%s' % (__main__.__file__, attr_name)
        else:
            if not self.routes:
                raise RuntimeError('cannot run this app. mounted somewhere?')

            kwargs['app'] = None

            if hasattr(__main__, '__file__'):
                kwargs['app_dir'], basename = os.path.split(
                    os.path.abspath(__main__.__file__)
                )
                kwargs['module_name'] = os.path.splitext(basename)[0]
            else:
                kwargs['app_dir'] = os.getcwd()
                kwargs['module_name'] = '__main__'

            if kwargs['log_level'] in ('DEBUG', 'INFO'):
                print('Routes:')

                for routes in self.routes.values():
                    for pattern, func, kw, _ in routes:
                        print(
                            '  %s -> %s(%s)' %
                            (pattern,
                             func.__name__,
                             ', '.join('%s=%s' % item for item in kw.items()))
                        )

                print()

        if host is None:
            if not self.ports:
                raise ValueError(
                    'with host=None, listen() must be called first'
                )

            host = 'localhost'
        else:
            self.listen(port, host=host, **kwargs)

        if worker_num < 1:
            try:
                worker_num = len(os.sched_getaffinity(0))
            except AttributeError:
                worker_num = os.cpu_count() or 1

        locks = [mp.Lock() for _ in range(kwargs['thread_pool_size'])]
        socks = {}
        print('Options:')

        for (_host, _port), options in self.ports.items():
            if _host is None:
                _host = host

            if _port is None:
                _port = port

            options = {**kwargs, **options}
            print(
                '  run(host=%s, port=%d, worker_num=%d, %s)' %
                (_host,
                 _port,
                 worker_num,
                 ', '.join('%s=%s' % item for item in options.items()))
            )

            args = (_host, _port)

            if options.get('reuse_port', hasattr(socket, 'SO_REUSEPORT')):
                sock = None
            else:
                sock = self.create_sock(_host, _port, reuse_port=False)
                socks[args] = sock

            for _ in range(options.get('worker_num', worker_num)):
                self.manager.spawn(
                    self._worker,
                    args=args,
                    kwargs=dict(options, _locks=locks, _sock=sock),
                    exit_cb=self._handle_reload
                )

        print('-' * terminal_width)
        print('%s main (pid %d) is running ' % (server_name, os.getpid()))

        try:
            self.manager.wait(timeout=kwargs['shutdown_timeout'])
        finally:
            for sock in socks.values():
                self.close_sock(sock)
