#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: nggit
# Description: A simple WebSocket Chat with HTML and vanilla JS.

import time

from tremolo import Application
from tremolo.utils import html_escape

app = Application()

sockets = []

@app.route('/')
async def ws_handler(request, websocket=None, stream=False):
    """A hybrid handler.

    Normally, you should separate the http:// and ws:// handlers individually.
    """
    if websocket is not None:
        # an upgrade request is received.
        # accept it by sending the "101 Switching Protocols"
        await websocket.accept()
        sockets.append(websocket)

        while True:
            message = await websocket.receive()
            # send back the received message
            for socket in sockets:
                await socket.send(
                    '[%s] Guest%s: %s' % (time.strftime('%H:%M:%S'),
                                          request.client[1], message)
                )

    # not an upgrade request. show the html page
    yield b"""\
    <!DOCTYPE html><html lang="en"><head><title>WebSocket Chat</title></head>
    <body>
        <h1>WebSocket Chat</h1>
        <form>
            <input type="text" id="message" autocomplete="off" />
            <button type="button" id="send">Send</button>
        </form>
        <ul id="messages"></ul>
        <script>
    """
    ws_scheme = b'wss' if request.scheme == b'https' else b'ws'

    yield b"var socket = new WebSocket('%s://%s/');" % (
        ws_scheme, html_escape(request.host))
    yield b"""
            var messages = document.getElementById('messages');
            var form = document.querySelector('form');

            socket.onmessage = function(event) {
                var message = document.createElement('li');
                message.textContent = event.data;
                messages.insertBefore(message, messages.firstChild);
            };

            form.onsubmit = (e) => {
                e.preventDefault()
                var message = document.getElementById('message');

                if (message) {
                    socket.send(message.value);
                    message.value = '';
                }
            };
        </script>
    </body>
    </html>
    """


if __name__ == '__main__':
    # don't forget to disable debug and reload on production!
    app.run('0.0.0.0', 8000, debug=True, reload=True)
