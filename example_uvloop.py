#!/usr/bin/env python3

import tremolo


async def app(scope, receive, send):
    assert scope['type'] == 'http'

    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [
            (b'content-type', b'text/plain'),
        ]
    })
    await send({
        'type': 'http.response.body',
        'body': b'Hello world!'
    })


if __name__ == '__main__':
    tremolo.run(app, host='0.0.0.0', port=8000, debug=True, loop='uvloop')
