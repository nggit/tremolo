#!/usr/bin/env python
# SPDX-License-Identifier: MIT
# Author: Zenen Treadwell (https://github.com/ZenenTreadwell)
# Description: https://github.com/nggit/tremolo/pull/275

import asyncio
import json

from tremolo import Application

app = Application()
listeners = {}


@app.route('/')
async def index(request, response, **server):
    try:
        [s] = request.cookies.get('session')
        if s not in listeners:
            raise TypeError
    except TypeError:
        s = request.uid().hex()
        response.set_cookie('session', s, expires=3600)

    html = '''
    <body>
        <p>The password is 'tremolo'</p>
        <form method="post" action="login" id="form">
            <label for="password">Enter password:</label>
            <input name="password" type="password" />
            <button>Login</button>
        </form>
        <button onclick='fetch("/ping")'>Ping Everyone</button>
        <div class="notifications"></div>
        <script>
        const form = document.querySelector('#form')
        form.addEventListener('submit', (e) => {
            e.preventDefault()
            const data = {
                password: form.querySelector('input').value
            }

            const form_data = new FormData(form)
            form.reset()
            const res = fetch('/login', {
                method: "POST",
                body: new URLSearchParams(form_data)
            })
        })

        const events = new EventSource('/notifications')
        events.addEventListener('notify', (e) => {
            const data = JSON.parse(e.data)
            const n = document.createElement('div')
            n.innerHTML = `${data.text}`
            n.classList.add('notification')
            n.classList.add(data.class)
            const box = document.querySelector('.notifications')
            box.appendChild(n)

            setTimeout(() => n.classList.add('faded'), 1500)
            setTimeout(() => n.remove(), 2000)

        })
        </script>
        <style>
        .notifications {
            position: absolute;
            display: flex;
            flex-direction: column;
            gap: 1em;
            bottom: 1em;
            right: 1em;
        }

        .notifications div {
            color: white;
            padding: 0.5em;
            box-shadow: 0.1em 0.1em 0.5em grey;
        }

        .notifications div.message {
            background: green;
        }

        .notifications div.error {
            background: red;
        }

        .faded {
            opacity: 0;
            animation: fade 0.4s;
        }

        @keyframes fade {
            0% {
                opacity: 1;
            }

            100% {
                opacity: 0;
            }
        }
        </style>
    </body>
    '''

    return html


@app.route('/notifications$')
async def notify(request, sse=None, **server):
    try:
        [s] = request.cookies.get('session')
    except TypeError:
        return None

    if sse:
        msg = {'text': 'listening', 'class': 'message'}
        await sse.send(json.dumps(msg).encode(), event='notify')

        queue = asyncio.Queue(maxsize=1)
        listeners[s] = queue

        try:
            while True:
                ev, data = await queue.get()
                msg = json.dumps(data).encode()
                await sse.send(msg, event=ev)
        finally:  # the client has gone or queue.get() has timed out, clean up
            listeners.pop(s, None)
            await sse.close()  # no-op on a client who has gone


@app.route('/login$')
async def login(request):
    data = await request.form()
    [password] = data.get('password') or [None]

    if password == "tremolo":
        notification = {'text': 'correct password', 'class': 'message'}
    else:
        notification = {'text': 'incorrect password', 'class': 'error'}

    try:
        [s] = request.cookies.get('session')
        queue = listeners[s]
        queue.put_nowait(['notify', notification])
        return 'login'

    except TypeError:
        return None


@app.route('/ping$')
async def ping(request):
    notification = {'text': 'ping!', 'class': 'message'}
    for queue in listeners.values():
        queue.put_nowait(['notify', notification])

    return f'ping to {len(listeners)} listeners'


if __name__ == "__main__":
    app.run('0.0.0.0', 8002, debug=True, app_handler_timeout=600)
