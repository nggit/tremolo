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

from functools import wraps  # noqa: E402
from importlib import import_module, reload as reload_module  # noqa: E402
from shutil import get_terminal_size  # noqa: E402

from . import __version__  # noqa: E402
from .managers import ProcessManager  # noqa: E402
from .routes import Routes  # noqa: E402
from .utils import (  # noqa: E402
    file_signature, getoptions, log_date, memory_usage, server_date
)
from .lib.connections import KeepAliveConnections  # noqa: E402
from .lib.contexts import WorkerContext  # noqa: E402
from .lib.locks import ServerLock  # noqa: E402

_REUSEPORT_OR_REUSEADDR = {
    False: socket.SO_REUSEADDR,
    True: getattr(socket, 'SO_REUSEPORT', socket.SO_REUSEADDR)
}


class Tremolo:
    def __init__(self, name=None):
        self.logger = None if name is None else logging.getLogger(name)
        self.context = WorkerContext()
        self.manager = ProcessManager()
        self.routes = Routes()
        self.middlewares = {
            'connect': [],
            'close': [],
            'request': [],
            'response': []
        }
        self.hooks = {
            'worker_start': [],
            'worker_stop': []
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

    def route(self, path):
        if isinstance(path, int):
            return self.error(path)

        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self.routes.add(wrapper, path, getoptions(func))
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
                        h[0], wrapper, dict(h[2], **getoptions(func))
                    )
                    break

            return wrapper

        return decorator

    def hook(self, name, *args, priority=999):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self.add_hook(wrapper, name, priority)
            return wrapper

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])

        return decorator

    def on_worker_start(self, *args, **kwargs):
        return self.hook('worker_start', *args, **kwargs)

    def on_worker_stop(self, *args, **kwargs):
        return self.hook('worker_stop', *args, **kwargs)

    def middleware(self, name, *args, priority=999):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self.add_middleware(wrapper, name, priority, getoptions(func))
            return wrapper

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])

        return decorator

    def on_connect(self, *args, **kwargs):
        return self.middleware('connect', *args, **kwargs)

    def on_close(self, *args, **kwargs):
        return self.middleware('close', *args, **kwargs)

    def on_request(self, *args, **kwargs):
        return self.middleware('request', *args, **kwargs)

    def on_response(self, *args, **kwargs):
        return self.middleware('response', *args, **kwargs)

    def add_hook(self, func, name='worker_start', priority=999):
        if name not in self.hooks:
            raise ValueError('%s is not one of the: %s' %
                             (name, ', '.join(self.hooks)))

        self.hooks[name].append((priority, func))
        self.hooks[name].sort(key=lambda item: item[0],
                              reverse=name == 'worker_stop')

    def add_middleware(self, func, name='request', priority=999, kwargs=None):
        if name not in self.middlewares:
            raise ValueError('%s is not one of the: %s' %
                             (name, ', '.join(self.middlewares)))

        self.middlewares[name].append(
            (priority, func, kwargs or getoptions(func))
        )
        self.middlewares[name].sort(key=lambda item: item[0],
                                    reverse=name in ('close', 'response'))

    def listen(self, port, host=None, **options):
        if not isinstance(port, int):
            # assume it's a UNIX socket path
            host = port
            port = None

        if (host, port) in self.ports:
            return False

        self.ports[(host, port)] = options
        return (host, port) in self.ports

    async def _serve(self, host, port, **kwargs):
        options = self.context.options
        options.update(kwargs)
        backlog = options.get('backlog', 100)

        if hasattr(options['_sock'], 'share'):
            # Windows
            sock = socket.fromshare(options['_sock'].share(os.getpid()))
        else:
            # Linux
            sock = self.create_sock(host, port, options['reuse_port'])

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

        if isinstance(host, str):
            host = host.encode('latin-1')

        lock = ServerLock(options['_locks'], loop=self.loop)
        connections = KeepAliveConnections(
            maxlen=options.get('keepalive_connections', 512)
        )
        self.context.update(connections=connections)

        if options['app'] is None:
            from .http_server import HTTPServer as Server

            self.routes.compile()

            for _, func in self.hooks['worker_start']:
                if await func(globals=self.context,
                              context=self.context,
                              app=self,
                              loop=self.loop,
                              logger=self.logger):
                    break
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

            if server_name != b'':
                server_name += b' (ASGI)'

            options['state'] = {}
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
        if self.context.options['app'] is None:
            i = len(self.hooks['worker_stop'])

            while i > 0:
                i -= 1

                if await self.hooks['worker_stop'][i][1](
                        globals=self.context,
                        context=self.context,
                        app=self,
                        loop=self.loop,
                        logger=self.logger):
                    break
        else:
            self.context.lifespan.shutdown()
            exc = await self.context.lifespan.exception(
                timeout=self.context.options['shutdown_timeout'] / 2
            )

            if exc:
                self.logger.error(exc)

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
            sock.setsockopt(socket.SOL_SOCKET,
                            _REUSEPORT_OR_REUSEADDR[reuse_port], 1)
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
                    if isinstance(attr, self.__class__):
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

    def run(self, host=None, port=0, reuse_port=True, worker_num=1, **kwargs):
        kwargs['reuse_port'] = reuse_port
        kwargs['log_level'] = kwargs.get('log_level', 'DEBUG').upper()
        kwargs.setdefault('shutdown_timeout', 30)
        server_name = kwargs.get('server_name', 'Tremolo')
        terminal_width = min(get_terminal_size()[0], 72)

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
                    for route in routes:
                        pattern, func, kw = route

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
            raise ValueError('worker_num must be greater than 0')

        try:
            worker_num = min(worker_num, len(os.sched_getaffinity(0)))
        except AttributeError:
            worker_num = min(worker_num, os.cpu_count() or 1)

        locks = [mp.Lock() for _ in range(kwargs.get('locks', 16))]
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
            socks[args] = self.create_sock(_host, _port, options['reuse_port'])

            for _ in range(options.get('worker_num', worker_num)):
                self.manager.spawn(
                    self._worker,
                    args=args,
                    kwargs=dict(options, _locks=locks, _sock=socks[args]),
                    exit_cb=self._handle_reload
                )

        print('-' * terminal_width)
        print('%s main (pid %d) is running ' % (server_name, os.getpid()))

        try:
            self.manager.wait(timeout=kwargs['shutdown_timeout'])
        finally:
            for sock in socks.values():
                self.close_sock(sock)
