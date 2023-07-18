#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import time
import unittest

import tremolo

from tests.http_server import app, HTTP_HOST, HTTP_PORT
from tests.asgi_server import app as asgi_app
from tests.asgi_server import ASGI_PORT

if __name__ == '__main__':
    mp.set_start_method('spawn')
    processes = []

    processes.append(mp.Process(
        target=app.run,
        kwargs=dict(host=HTTP_HOST, port=HTTP_PORT, debug=False))
    )
    processes.append(mp.Process(
        target=tremolo.run,
        kwargs=dict(app=asgi_app, host=HTTP_HOST, port=ASGI_PORT, debug=False))
    )

    for p in processes:
        p.start()

    try:
        suite = unittest.TestLoader().discover('tests')
        unittest.TextTestRunner().run(suite)
    finally:
        TIMEOUT = 30
        FACTOR = 10

        for p in processes:
            for _ in range(TIMEOUT * FACTOR):
                if p.is_alive():
                    os.kill(p.pid, signal.SIGINT)
                    p.join()
                else:
                    break

                time.sleep(1 / FACTOR)
            else:
                p.terminate()
