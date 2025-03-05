#!/usr/bin/env python3

import tremolo


async def app(scope, receive, send):
    assert scope['type'] == 'http'

    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [
            (b'content-type', b'text/plain')
        ]
    })

    body = b''

    while True:
        message = await receive()
        body += message.get('body', b'')

        if not message.get('more_body', False):
            break

    await send({
        'type': 'http.response.body',
        'body': body or b'Hello, World!'
    })


if __name__ == '__main__':
    tremolo.run(app, host='0.0.0.0', port=8000, debug=True, loop='uvloop')
