#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import unittest

import tremolo

from tests.http_server import app, HTTP_HOST, HTTP_PORT, LIMIT_MEMORY
from tests.asgi_server import app as asgi_app
from tests.asgi_server import ASGI_HOST, ASGI_PORT


def main():
    mp.set_start_method('spawn', force=True)
    processes = []

    processes.append(mp.Process(
        target=app.run,
        kwargs=dict(host=HTTP_HOST,
                    port=HTTP_PORT,
                    limit_memory=LIMIT_MEMORY,
                    debug=False,
                    reload=True,
                    shutdown_timeout=5,
                    loop='asyncio.SelectorEventLoop',
                    client_max_body_size=1048576,  # 1MiB
                    ws_max_payload_size=73728))
    )
    processes.append(mp.Process(
        target=tremolo.run,
        kwargs=dict(app=asgi_app, host=ASGI_HOST, port=ASGI_PORT, debug=False,
                    keepalive_timeout=2))
    )

    for p in processes:
        p.start()

    try:
        suite = unittest.TestLoader().discover('tests')
        unittest.TextTestRunner().run(suite)
    finally:
        for p in processes:
            if p.is_alive():
                os.kill(p.pid, signal.SIGINT)
                p.join()


if __name__ == '__main__':
    main()
