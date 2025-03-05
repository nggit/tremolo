
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
