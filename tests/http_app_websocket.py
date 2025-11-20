#!/usr/bin/env python3

import os
import sys

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo import Application  # noqa: E402

app = Application()


@app.route('/ws')
async def ws_handler(websocket=None):
    if websocket.request.query_string == b'close':
        await websocket.accept()

        # test send close manually
        await websocket.close()

        # this suggests that you want to handle the disconnection manually
        return True

    if websocket.request.query_string == b'ping':
        await websocket.accept()

        # WebSocket.recv automatically sends pong
        await websocket.recv()
    else:
        # await websocket.accept()
        # while True: data = await websocket.receive()
        #
        # async iterator implicitly performs WebSocket.accept
        async for data in websocket:
            await websocket.send(data)
            break


if __name__ == '__main__':
    app.run('127.0.0.1', port=28000, debug=True, reload=True,
            client_max_body_size=1048576, ws_max_payload_size=73728)
