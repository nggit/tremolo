# Copyright (c) 2023 nggit

__all__ = ('file_signature', 'getoptions', 'html_escape', 'is_async',
           'log_date', 'memory_usage', 'parse_args', 'parse_fields',
           'parse_int', 'print_logo', 'server_date', 'to_sync')

import os  # noqa: E402
import stat  # noqa: E402
import sys  # noqa: E402

from asyncio import run_coroutine_threadsafe as run_coroutine  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from html import escape  # noqa: E402
from inspect import iscoroutinefunction, isasyncgenfunction  # noqa: E402
from urllib.parse import unquote_to_bytes as unquote  # noqa: E402


def file_signature(path):
    st = os.stat(path)

    return (stat.S_IFMT(st.st_mode), st.st_size, st.st_mtime)


def getoptions(func):
    options = {}
    argcount = func.__code__.co_argcount

    if func.__defaults__ is not None:
        argcount -= len(func.__defaults__)

    for name in func.__code__.co_varnames[:argcount]:
        options[name] = None

    for i, name in enumerate(func.__code__.co_varnames[
                                 argcount:func.__code__.co_argcount]):
        options[name] = func.__defaults__[i]

    return options


def html_escape(data):
    if isinstance(data, str):
        return escape(data)

    return (data.replace(b'&', b'&amp;')
            .replace(b'<', b'&lt;')
            .replace(b'>', b'&gt;')
            .replace(b'"', b'&quot;'))


def is_async(func):
    return iscoroutinefunction(func) or isasyncgenfunction(func)


def log_date():
    return datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')


def memory_usage(pid=0):
    if not pid:
        pid = os.getpid()

    try:
        with open('/proc/%d/statm' % pid, 'r') as f:
            return int(f.read().split()[1]) * os.sysconf('SC_PAGESIZE') // 1024
    except FileNotFoundError:
        # non-Linux
        return -1


def parse_args(**callbacks):
    options = {'host': '127.0.0.1', 'port': 8000, 'ssl': {}}
    context = {'options': options}

    for i in range(len(sys.argv)):
        name = sys.argv[i - 1].lstrip('-').replace('-', '_')

        if sys.argv[i - 1] == '--no-ws':
            options['ws'] = False
        elif sys.argv[i - 1] in ('--debug', '--experimental', '--reload'):
            options[name] = True
        elif sys.argv[i - 1] in ('--host',
                                 '--log-level',
                                 '--log-fmt',
                                 '--loop',
                                 '--server-name',
                                 '--root-path'):
            options[name] = sys.argv[i]
        elif sys.argv[i - 1] in ('--port',
                                 '--worker-num',
                                 '--thread-pool-size',
                                 '--limit-memory',
                                 '--backlog',
                                 '--download-rate',
                                 '--upload-rate',
                                 '--buffer-size',
                                 '--ws-max-payload-size',
                                 '--client-max-body-size',
                                 '--client-max-header-size',
                                 '--max-queue-size',
                                 '--request-timeout',
                                 '--keepalive-timeout',
                                 '--keepalive-connections',
                                 '--app-handler-timeout',
                                 '--app-close-timeout',
                                 '--shutdown-timeout'):
            try:
                options[name] = int(sys.argv[i])
            except ValueError:
                print(
                    'Invalid %s value "%s". It must be a number' %
                    (sys.argv[i - 1], sys.argv[i])
                )
                sys.exit(1)
        elif sys.argv[i - 1] == '--ssl-cert':
            options['ssl']['cert'] = sys.argv[i]
        elif sys.argv[i - 1] == '--ssl-key':
            options['ssl']['key'] = sys.argv[i]
        elif sys.argv[i - 1].startswith('-'):
            if name in callbacks:
                code = callbacks[name](value=sys.argv[i], **context)

                if code is not None:
                    sys.exit(code)
            else:
                print('Unrecognized option "%s"' % sys.argv[i - 1])
                sys.exit(1)

    return options


def parse_fields(data, separator=b';', split=b'=', max_fields=100):
    if len(separator) != 1:
        raise ValueError('separator must be a single one-byte character')

    end = len(data)

    while max_fields > 0:
        start = data.rfind(separator, 0, end) + 1

        if split:
            name, _, value = data[start:end].partition(split)

            if name:
                yield (name.strip().lower(), unquote(value.strip(b' \t"')))
        else:
            yield data[start:end].strip().lower()

        if start == 0:
            break

        end = start - 1
        max_fields -= 1


def parse_int(string, base=10):
    if not isinstance(string, (bytes, bytearray)) or not 0 < len(string) <= 16:
        raise ValueError('string must be bytes-like and <=16 in length')

    if string == b'0':
        return 0

    if string.startswith(b'0'):
        raise ValueError('string cannot contain leading zeros')

    total = 0

    for c in string:
        total = total * base + int(chr(c), base)

    return total


def print_logo():
    BLUE = '\033[0;34m'
    RESET = '\033[0m'

    try:
        print(f'\n                                {BLUE}▄▄██{RESET}')
    except UnicodeEncodeError:
        return

    print(f'  █                             {BLUE}▀▀  {RESET}')
    print(f'  █▀▀  █▄▀▀ ▄▀▀▀▄ ▄▀▀█▀▀▄ ▄▀▀▀▄ {BLUE}▄▄██{RESET} ▄▀▀▀▄')
    print(f'  █    █    █▄▄▄█ █  █  █ █   █ {BLUE}▀▀  {RESET} █   █')
    print(f'  █    █    █     █  █  █ █   █ {BLUE}▄▄██{RESET} █   █')
    print(f'   ▀▀▀ ▀     ▀▀▀  ▀  ▀  ▀  ▀▀▀  {BLUE}▀▀  {RESET}  ▀▀▀ \n')


def server_date():
    return datetime.now(timezone.utc).strftime(
        '%a, %d %b %Y %H:%M:%S GMT').encode('latin-1')


class AsyncToSyncWrapper:
    def __init__(self, obj, loop):
        self.__wrapped__ = obj
        self.loop = loop

    def __getattr__(self, name):
        attr = getattr(self.__wrapped__, name)

        if iscoroutinefunction(attr):
            def func(*args, **kwargs):
                return run_coroutine(attr(*args, **kwargs), self.loop).result()

            return func

        if isasyncgenfunction(attr):
            def generator(*args, **kwargs):
                agen = attr(*args, **kwargs)

                while True:
                    try:
                        fut = run_coroutine(agen.__anext__(), self.loop)
                        yield fut.result()
                    except StopAsyncIteration:
                        break

            return generator

        return attr


to_sync = AsyncToSyncWrapper
