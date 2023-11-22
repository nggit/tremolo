# Copyright (c) 2023 nggit

import sys

from tremolo import Tremolo

server = Tremolo()
options = {'host': '127.0.0.1', 'port': 8000, 'ssl': {}}

for i in range(len(sys.argv)):
    if sys.argv[i - 1] == '--help':
        print('Usage: python3 -m tremolo [OPTIONS] APP')
        print()
        print('Example:')
        print('  python3 -m tremolo example:app')
        print('  python3 -m tremolo /path/to/example.py')
        print('  python3 -m tremolo /path/to/example.py:myapp')
        print('  python3 -m tremolo --debug --port 8080 example:app')
        print()
        print('Options:')
        print('  --host                    Listen host. Defaults to "127.0.0.1"')  # noqa: E501
        print('  --port                    Listen port. Defaults to 8000')
        print('  --bind                    Address to bind.')
        print('                            Instead of using --host or --port')
        print('                            E.g. "127.0.0.1:8000" or "/tmp/file.sock"')  # noqa: E501
        print('                            Multiple binds can be separated by commas')  # noqa: E501
        print('                            E.g. "127.0.0.1:8000,:8001"')
        print('  --worker-num              Number of worker processes. Defaults to 1')  # noqa: E501
        print('  --backlog                 Maximum number of pending connections')  # noqa: E501
        print('                            Defaults to 100')
        print('  --ssl-cert                SSL certificate location')
        print('                            E.g. "/path/to/fullchain.pem"')
        print('  --ssl-key                 SSL private key location')
        print('                            E.g. "/path/to/privkey.pem"')
        print('  --debug                   Enable debug mode')
        print('                            Intended for development')
        print('  --reload                  Enable auto reload on code changes')
        print('                            Intended for development')
        print('  --no-ws                   Disable built-in WebSocket support')
        print('  --log-level               Defaults to "DEBUG". See')
        print('                            https://docs.python.org/3/library/logging.html#levels')  # noqa: E501
        print('  --download-rate           Limits the sending speed to the client')  # noqa: E501
        print('                            Defaults to 1048576, which means 1MiB/s')  # noqa: E501
        print('  --upload-rate             Limits the upload / POST speed')
        print('                            Defaults to 1048576, which means 1MiB/s')  # noqa: E501
        print('  --buffer-size             Defaults to 16384, or 16KiB')
        print('  --client-max-body-size    Defaults to 2 * 1048576, or 2MiB')
        print('  --client-max-header-size  Defaults to 8192, or 8KiB')
        print('  --max-queue-size          Maximum number of buffers in the queue')  # noqa: E501
        print('                            Defaults to 128')
        print('  --request-timeout         Defaults to 30 (seconds)')
        print('  --keepalive-timeout       Defaults to 30 (seconds)')
        print('  --keepalive-connections   Maximum number of keep-alive connections')  # noqa: E501
        print('                            Defaults to 512 (connections/worker)')  # noqa: E501
        print('  --app-handler-timeout     Kill the app if it takes too long to finish')  # noqa: E501
        print('                            Upgraded connection/scope will not be affected')  # noqa: E501
        print('                            Defaults to 120 (seconds)')
        print('  --app-close-timeout       Kill the app if it does not exit within this timeframe,')  # noqa: E501
        print('                            from when the client is disconnected')  # noqa: E501
        print('                            Defaults to 30 (seconds)')
        print('  --server-name             Set the "Server" field in the response header')  # noqa: E501
        print('  --root-path               Set the ASGI root_path. Defaults to ""')  # noqa: E501
        print('  --help                    Show this help and exit')
        sys.exit()
    elif sys.argv[i - 1] == '--no-ws':
        options['ws'] = False
    elif sys.argv[i - 1] in ('--debug', '--reload'):
        options[sys.argv[i - 1].lstrip('-').replace('-', '_')] = True
    elif sys.argv[i - 1] in ('--host',
                             '--log-level',
                             '--server-name',
                             '--root-path'):
        options[sys.argv[i - 1].lstrip('-').replace('-', '_')] = sys.argv[i]
    elif sys.argv[i - 1] in ('--port',
                             '--worker-num',
                             '--backlog',
                             '--download-rate',
                             '--upload-rate',
                             '--buffer-size',
                             '--client-max-body-size',
                             '--client-max-header-size',
                             '--max-queue-size',
                             '--request-timeout',
                             '--keepalive-timeout',
                             '--keepalive-connections',
                             '--app-handler-timeout',
                             '--app-close-timeout'):
        try:
            options[sys.argv[i - 1].lstrip('-').replace('-', '_')] = int(sys.argv[i])  # noqa: E501
        except ValueError:
            print(
                'Invalid %s value "%s". It must be a number' % (
                    sys.argv[i - 1], sys.argv[i])
            )
            sys.exit(1)
    elif sys.argv[i - 1] == '--bind':
        options['host'] = None

        try:
            for bind in sys.argv[i].split(','):
                if ':\\' not in bind and ':' in bind:
                    host, port = bind.rsplit(':', 1)
                    server.listen(int(port), host=host.strip('[]') or None)
                else:
                    server.listen(bind)
        except ValueError:
            print('Invalid --bind value "%s"' % sys.argv[i])
            sys.exit(1)
    elif sys.argv[i - 1] == '--ssl-cert':
        options['ssl']['cert'] = sys.argv[i]
    elif sys.argv[i - 1] == '--ssl-key':
        options['ssl']['key'] = sys.argv[i]
    elif sys.argv[i - 1].startswith('-'):
        print('Unrecognized option "%s"' % sys.argv[i - 1])
        sys.exit(1)

if sys.argv[-1] != sys.argv[0] and not sys.argv[-1].startswith('-'):
    options['app'] = sys.argv[-1]

if __name__ == '__main__':
    if 'app' not in options:
        print('You must specify APP. Use "--help" for help')
        sys.exit(1)

    server.run(**options)
