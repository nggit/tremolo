#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import unittest

import tremolo

from tests.http_server import app, HTTP_HOST, HTTP_PORT
from tests.asgi_server import app as asgi_app
from tests.asgi_server import ASGI_HOST, ASGI_PORT


def main():
    mp.set_start_method('spawn')
    processes = []

    processes.append(mp.Process(
        target=app.run,
        kwargs=dict(host=HTTP_HOST,
                    port=HTTP_PORT,
                    debug=False,
                    reload=True,
                    loop='asyncio.SelectorEventLoop',
                    limit_memory=102400,  # 100MiB
                    client_max_body_size=1048576,  # 1MiB
                    ws_max_payload_size=73728))
    )
    processes.append(mp.Process(
        target=tremolo.run,
        kwargs=dict(app=asgi_app, host=ASGI_HOST, port=ASGI_PORT, debug=False))
    )

    for p in processes:
        p.start()

    try:
        suite = unittest.TestLoader().discover('tests')
        unittest.TextTestRunner().run(suite)
    finally:
        for p in processes:
            if p.is_alive():
                os.kill(p.pid, signal.SIGTERM)
                p.join()


if __name__ == '__main__':
    main()
