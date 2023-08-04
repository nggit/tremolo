#!/usr/bin/env python3

import time

from tremolo import Tremolo
from tremolo.exceptions import BadRequest

app = Tremolo()


@app.on_request
async def middleware_handler(**server):
    for char in b'&<>"\'':
        if char in server['request'].host:
            raise BadRequest('illegal host')

    # add more validations, CORS headers, etc if needed


@app.route('/')
async def ws_handler(websocket=None, request=None, **_):
    """A hybrid handler.

    Normally, you should separate http:// and ws:// respectively.
    """

    if websocket is not None:
        # an upgrade request is received.
        # accept it by sending the "101 Switching Protocols"
        await websocket.accept()

        while True:
            message = await websocket.receive()
            # send back the received message
            await websocket.send(
                '[{:s}] Guest{:d}: {:s}'.format(
                    time.strftime('%H:%M:%S'), request.client[1], message)
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
    yield b"\
        var socket = new WebSocket('ws://%s/');" % request.host
    yield b"""
            var messages = document.getElementById('messages');
            var sendButton = document.getElementById('send');

            socket.onmessage = function(event) {
                var message = document.createElement('li');
                message.textContent = event.data;
                messages.insertBefore(message, messages.firstChild);
            };

            sendButton.onclick = function() {
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
    # don't forget to disable debug on production!
    app.run('0.0.0.0', 8000, debug=True)
