#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: Anggit Arfanto
# Description: Sharing state between processes.

import multiprocessing as mp

from tremolo import Application

app = Application()


@app.route('/')
def hello(request, response, **server):
    g = server['globals']
    mystate = g.options['mystate']
    process = mp.current_process()

    if process.name not in mystate:
        mystate[process.name] = None
        return f'Detected {process.name}'

    return f'Hello from: {process.name}. Workers detected: {len(mystate)}'


if __name__ == '__main__':
    with mp.Manager() as manager:
        mystate = manager.dict()

        # `app.run()` accepts extra/arbitrary options
        app.run('0.0.0.0', 8000, debug=True, worker_num=4, keepalive_timeout=1,
                mystate=mystate)
