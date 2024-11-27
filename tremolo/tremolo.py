# Copyright (c) 2023 nggit

__all__ = ('Tremolo',)

import asyncio  # noqa: E402
import logging  # noqa: E402
import multiprocessing as mp  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import ssl  # noqa: E402
import sys  # noqa: E402

from functools import wraps  # noqa: E402
from importlib import import_module, reload as reload_module  # noqa: E402
from shutil import get_terminal_size  # noqa: E402

from . import __version__, handlers  # noqa: E402
from .managers import ProcessManager  # noqa: E402
from .utils import (  # noqa: E402
    file_signature, log_date, memory_usage, server_date
)
from .lib.connections import KeepAliveConnections  # noqa: E402
from .lib.contexts import WorkerContext  # noqa: E402
from .lib.locks import ServerLock  # noqa: E402

_REUSEPORT_OR_REUSEADDR = {
    True: getattr(socket, 'SO_REUSEPORT', socket.SO_REUSEADDR),
    False: socket.SO_REUSEADDR
}


class Tremolo:
    def __init__(self):
        self.routes = {
            0: [
                (400, handlers.error_400, {}),
                (404, handlers.error_404, dict(status=(404, b'Not Found'),
                                               stream=False)),
                # must be at the very end
                (500, handlers.error_500, {})
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
        self.hooks = {
            'worker_start': [],
            'worker_stop': []
        }
        self.ports = {}
        self.manager = ProcessManager()
        self.loop = None
        self.logger = None
        self._task = None

    def listen(self, port, host=None, **options):
        if not isinstance(port, int):
            # assume it's a UNIX socket path
            host = port
            port = None

        if (host, port) in self.ports:
            return False

        self.ports[(host, port)] = options
        return (host, port) in self.ports

    def route(self, path):
        if isinstance(path, int):
            return self.error(path)

        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self.add_route(wrapper, path, self.getoptions(func))
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

    def hook(self, name, priority=999):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self.add_hook(wrapper, name, priority)
            return wrapper

        return decorator

    def on_worker_start(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return self.hook('worker_start')(args[0])

        return self.hook('worker_start', **kwargs)

    def on_worker_stop(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return self.hook('worker_stop')(args[0])

        return self.hook('worker_stop', **kwargs)

    def middleware(self, name, priority=999):
        def decorator(func):
            @wraps(func)
            def wrapper(**kwargs):
                return func(**kwargs)

            self.add_middleware(
                wrapper, name, priority, self.getoptions(func)
            )
            return wrapper

        return decorator

    def on_connect(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('connect')(args[0])

        return self.middleware('connect', **kwargs)

    def on_close(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('close')(args[0])

        return self.middleware('close', **kwargs)

    def on_request(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('request')(args[0])

        return self.middleware('request', **kwargs)

    def on_response(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return self.middleware('response')(args[0])

        return self.middleware('response', **kwargs)

    def getoptions(self, func):
        options = {}
        arg_count = func.__code__.co_argcount

        if func.__defaults__ is not None:
            arg_count -= len(func.__defaults__)

        for i, name in enumerate(func.__code__.co_varnames[
                                     arg_count:func.__code__.co_argcount]):
            options[name] = func.__defaults__[i]

        return options

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
            (priority, func, kwargs or self.getoptions(func))
        )
        self.middlewares[name].sort(key=lambda item: item[0],
                                    reverse=name in ('close', 'response'))

    def add_route(self, func, path='/', kwargs=None):
        if not kwargs:
            kwargs = self.getoptions(func)

        if path.startswith('^') or path.endswith('$'):
            pattern = path.encode('latin-1')
            self.routes[-1].append((pattern, func, kwargs))
        else:
            path = path.split('?', 1)[0].strip('/').encode('latin-1')

            if path == b'':
                key = 1
                pattern = self.routes[1][0][0]
                self.routes[key] = [(pattern, func, kwargs)]
            else:
                parts = path.split(b'/', 254)
                key = bytes([len(parts)]) + parts[0]
                pattern = b'^/+%s(?:/+)?(?:\\?.*)?$' % path

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
        backlog = options.get('backlog', 100)

        if hasattr(options['_sock'], 'share'):
            # Windows
            sock = socket.fromshare(options['_sock'].share(os.getpid()))
        else:
            # Linux
            sock = self.create_sock(host, port, options['reuse_port'])

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

        lock = ServerLock(options['_locks'], loop=self.loop)
        connections = KeepAliveConnections(
            maxlen=options.get('keepalive_connections', 512)
        )
        context = WorkerContext()
        context.options.update(options)

        if options['app'] is None:
            from .http_server import HTTPServer as Server

            self.compile_routes(options['_routes'])

            for _, func in self.hooks['worker_start']:
                if (await func(globals=context,
                               context=context,
                               app=self,
                               loop=self.loop,
                               logger=self.logger)):
                    break
        else:
            from .asgi_lifespan import ASGILifespan
            from .asgi_server import ASGIServer as Server

            # 'module:app'               -> 'module:app'   (dir: os.getcwd())
            # '/path/to/module.py'       -> 'module:app'   (dir: '/path/to')
            # '/path/to/module.py:myapp' -> 'module:myapp' (dir: '/path/to')

            if (':\\' in options['app'] and options['app'].count(':') < 2 or
                    ':' not in options['app']):
                options['app'] += ':app'

            path, attr_name = options['app'].rsplit(':', 1)
            options['app_dir'], base_name = os.path.split(
                os.path.abspath(path))
            module_name = os.path.splitext(base_name)[0]

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

            context.options['_lifespan'] = ASGILifespan(
                options['app'], loop=self.loop, logger=self.logger
            )
            context.options['_lifespan'].startup()
            exc = await context.options['_lifespan'].exception(
                timeout=context.options['shutdown_timeout'] / 2
            )

            if exc:
                raise exc

        context.info['server_date'] = server_date()
        context.info['server_name'] = server_name

        server = await self.loop.create_server(
            lambda: Server(context,
                           loop=self.loop,
                           logger=self.logger,
                           lock=lock,
                           debug=options.get('debug', False),
                           ws=options.get('ws', True),
                           ws_max_payload_size=options.get(
                               'ws_max_payload_size', 2 * 1048576
                           ),
                           download_rate=options.get('download_rate', 1048576),
                           upload_rate=options.get('upload_rate', 1048576),
                           buffer_size=options.get('buffer_size', 16 * 1024),
                           client_max_body_size=options.get(
                               'client_max_body_size', 2 * 1048576
                           ),
                           client_max_header_size=options.get(
                               'client_max_header_size', 8192
                           ),
                           max_queue_size=options.get('max_queue_size', 128),
                           request_timeout=options.get('request_timeout', 30),
                           keepalive_timeout=options.get(
                               'keepalive_timeout', 30
                           ),
                           app_handler_timeout=options.get(
                               'app_handler_timeout', 120
                           ),
                           _connections=connections,
                           _app=options['app'],
                           _app_close_timeout=options.get(
                               'app_close_timeout', 30
                           ),
                           _root_path=options.get('root_path', ''),
                           _routes=options['_routes'],
                           _middlewares=options['_middlewares']),
            sock=sock, backlog=backlog, ssl=ssl_context)

        print(log_date(), end=' ')
        sys.stdout.flush()
        sys.stdout.buffer.write(
            b'%s worker (pid %d) is started at ' % (server_name, os.getpid())
        )

        if sock.family.name == 'AF_UNIX':
            print(sock.getsockname(), end='')
        else:
            print('%s port %d' % sock.getsockname()[:2], end='')

        if ssl_context is not None:
            sys.stdout.flush()
            sys.stdout.buffer.write(b' (https)')

        print()
        paths = [path for path in sys.path
                 if not options['app_dir'].startswith(path)]
        modules = {}
        limit_memory = options.get('limit_memory', 0)

        try:
            # serve forever
            while True:
                await asyncio.sleep(1)

                # update server date
                context.info['server_date'] = server_date()

                # detect code changes
                if 'reload' in options and options['reload']:
                    for module in (dict(modules) or sys.modules.values()):
                        if not hasattr(module, '__file__'):
                            continue

                        for path in paths:
                            if (module.__file__ is None or
                                    module.__file__.startswith(path)):
                                break
                        else:
                            if not os.path.exists(module.__file__):
                                if module in modules:
                                    del modules[module]

                                continue

                            sign = file_signature(module.__file__)

                            if module in modules:
                                if modules[module] == sign:
                                    # file not modified
                                    continue

                                modules[module] = sign
                            else:
                                modules[module] = sign
                                continue

                            self.logger.info('reload: %s', module.__file__)
                            sys.exit(3)

                if limit_memory > 0 and memory_usage() > limit_memory:
                    while context.tasks:
                        context.tasks.pop().cancel()

                    self.logger.error('memory limit exceeded')
                    sys.exit(1)
        except asyncio.CancelledError:
            self.logger.info('Shutting down')

            if context.tasks:
                _, pending = await asyncio.wait(
                    context.tasks,
                    timeout=context.options['shutdown_timeout'] / 2
                )
                for task in pending:
                    task.cancel()
        finally:
            server.close()

            try:
                while context.tasks:
                    await context.tasks.pop()

                await server.wait_closed()
                await self._worker_stop(context)
            finally:
                self.loop.stop()

    async def _worker_stop(self, context):
        if context.options['app'] is None:
            i = len(self.hooks['worker_stop'])

            while i > 0:
                i -= 1

                if (await self.hooks['worker_stop'][i][1](
                        globals=context,
                        context=context,
                        app=self,
                        loop=self.loop,
                        logger=self.logger)):
                    break
        else:
            context.options['_lifespan'].shutdown()
            exc = await context.options['_lifespan'].exception(
                timeout=context.options['shutdown_timeout'] / 2
            )

            if exc:
                self.logger.error(exc)

    def _handle_shutdown(self, signum, frame):
        self._task.cancel()

    def _worker(self, host, port, **kwargs):
        self.logger = logging.getLogger(mp.current_process().name)
        self.logger.setLevel(
            getattr(logging, kwargs['log_level'], logging.DEBUG)
        )

        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '[%(asctime)s] %(module)s: %(levelname)s: %(message)s'
        )

        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        loop_name = kwargs.get('loop', 'asyncio.')

        if '.' not in loop_name:
            loop_name += '.'

        # 'asyncio', '.', ''
        # 'asyncio', '.', 'SelectorEventLoop'
        module_name, _, class_name = loop_name.rpartition('.')
        module = import_module(module_name or 'asyncio')
        self.loop = getattr(module, class_name or 'new_event_loop')()

        asyncio.set_event_loop(self.loop)
        self._task = self.loop.create_task(self._serve(host, port, **kwargs))

        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        try:
            self.loop.run_forever()
        finally:
            try:
                if not self._task.cancelled():
                    exc = self._task.exception()

                    # to avoid None, SystemExit, etc. for being printed
                    if isinstance(exc, Exception):
                        self.logger.error(exc)
            finally:
                self.loop.close()

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
                    if (hasattr(module, '__file__') and
                            module.__name__ not in ('__main__',
                                                    '__mp_main__',
                                                    'tremolo') and
                            not module.__name__.startswith('tremolo.') and
                            module.__file__ is not None and
                            module.__file__.startswith(kwargs['app_dir']) and
                            os.path.exists(module.__file__)):
                        reload_module(module)

                if kwargs['module_name'] in sys.modules:
                    _module = sys.modules[kwargs['module_name']]
                else:
                    _module = import_module(kwargs['module_name'])

                # we need to update/rebind objects like
                # routes, middleware, etc.
                for attr_name in dir(_module):
                    if attr_name.startswith('__'):
                        continue

                    attr = getattr(_module, attr_name)

                    if isinstance(attr, self.__class__):
                        self.__dict__.update(attr.__dict__)

                # update some references
                kwargs['_routes'] = self.routes
                kwargs['_middlewares'] = self.middlewares
        elif process.exitcode != 0:
            print(
                'A worker process died (%d). Restarting...' % process.exitcode
            )

        if process.exitcode == 0:
            print('pid %d terminated (0)' % process.pid)
        else:
            # this is a workaround, especially on Windows
            # to trigger renew socket
            kwargs['_sock'] = None

            self.manager.spawn(
                self._worker, args=args, kwargs=kwargs,
                exit_cb=self._handle_reload
            )

    def run(self, host=None, port=0, reuse_port=True, worker_num=1, **kwargs):
        kwargs['reuse_port'] = reuse_port
        kwargs['log_level'] = kwargs.get('log_level', 'DEBUG').upper()
        kwargs['shutdown_timeout'] = kwargs.get('shutdown_timeout', 30)
        server_name = kwargs.get('server_name', 'Tremolo')
        terminal_width = min(get_terminal_size()[0], 72)

        print(
            'Starting %s (tremolo %s, %s %d.%d.%d, %s)' % (
                server_name,
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

                for attr_name in dir(__main__):
                    if attr_name.startswith('__'):
                        continue

                    if getattr(__main__, attr_name) == kwargs['app']:
                        break
                else:
                    attr_name = 'app'

                kwargs['app'] = '%s:%s' % (__main__.__file__, attr_name)

            locks = []
        else:
            kwargs['app'] = None
            locks = [mp.Lock() for _ in range(kwargs.get('locks', 16))]

            if hasattr(__main__, '__file__'):
                kwargs['app_dir'], base_name = os.path.split(
                    os.path.abspath(__main__.__file__)
                )
                kwargs['module_name'] = os.path.splitext(base_name)[0]
            else:
                kwargs['app_dir'] = os.getcwd()
                kwargs['module_name'] = '__main__'

            if kwargs['log_level'] in ('DEBUG', 'INFO'):
                print('Routes:')

                for routes in self.routes.values():
                    for route in routes:
                        pattern, func, kwds = route

                        print(
                            '  %s -> %s(%s)' % (
                                pattern,
                                func.__name__,
                                ', '.join(
                                    '%s=%s' % item for item in kwds.items()))
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

        socks = {}
        print('Options:')

        for (_host, _port), options in self.ports.items():
            if _host is None:
                _host = host

            if _port is None:
                _port = port

            options = {**kwargs, **options}
            print(
                '  run(host=%s, port=%d, worker_num=%d, %s)' % (
                    _host,
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
                    kwargs=dict(options, _locks=locks, _sock=socks[args],
                                _routes=self.routes,
                                _middlewares=self.middlewares),
                    exit_cb=self._handle_reload
                )

        print('-' * terminal_width)
        print('%s main (pid %d) is running ' % (server_name, os.getpid()))
        self.manager.wait(timeout=kwargs['shutdown_timeout'])

        for sock in socks.values():
            self.close_sock(sock)
