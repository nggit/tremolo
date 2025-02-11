#!/usr/bin/env python3

__all__ = ('app', 'HTTP_HOST', 'HTTP_PORT', 'TEST_FILE', 'LIMIT_MEMORY')

import asyncio  # noqa: E402
import concurrent.futures  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo import Application  # noqa: E402
from tremolo.exceptions import BadRequest  # noqa: E402
from tremolo.utils import memory_usage  # noqa: E402

if sys.implementation.name == 'cpython' and sys.platform == 'linux':
    LIMIT_MEMORY = 51200  # 50MiB
else:
    LIMIT_MEMORY = 0

HTTP_HOST = '127.0.0.1'
HTTP_PORT = 28000
TEST_FILE = __file__

app = Application()


@app.on_worker_start  # priority=999 (low)
async def worker_start(**worker):
    g = worker['context']
    # or:
    # g = worker['globals']

    assert g.options['client_max_body_size'] == 1048576

    g.shared = 0
    g.socket_family = 'AF_UNIX'


@app.on_worker_start(priority=1)  # high
async def worker_start2(**worker):
    assert worker['app'].hooks['worker_start'][0][1] is worker_start2


@app.on_worker_stop(priority=1)
async def worker_stop2(**worker):
    assert worker['app'].hooks['worker_stop'][-1][1] is worker_stop2


@app.on_worker_stop
async def worker_stop(**worker):
    g = worker['context']

    if g.socket_family == 'AF_UNIX':
        assert g.shared == 0
    else:
        assert g.shared > 0


@app.on_connect
async def on_connect(**server):
    server['context'].foo = 'bar'

    return True


@app.on_close
async def on_close(**server):
    assert server['context'].foo == 'bar'
    server['globals'].options['max_queue_size'] = 128

    return True


@app.on_request(priority=1000)
async def on_request2(request, **_):
    assert request.protocol.options['max_queue_size'] == 123
    assert request.ctx.foo == 'baz'


@app.on_request
async def on_request(**server):
    request = server['request']
    response = server['response']
    g = server['globals']
    g.shared += 1
    g.socket_family = request.socket.family.name
    request.protocol.options['max_queue_size'] = 123
    request.ctx.foo = 'baz'

    if not request.is_valid:
        raise BadRequest

    if request.method not in (b'GET', b'POST', b'HEAD'):
        response.set_status(405, 'Method Not Allowed')
        response.set_content_type('text/plain')

        return b'Request method %s is not supported!' % request.method

    # these should appear in the next middlewares or handlers
    response.set_header('X-Foo', 'bar')
    response.set_cookie('sess', 'www')


@app.on_response
async def on_response(**server):
    response = server['response']

    assert response.headers[b'x-foo'] == [b'X-Foo: bar']
    assert b'Set-Cookie: sess=www; ' in response.headers[b'set-cookie'][0]

    response.set_header(b'X-Foo', b'baz')

    if response.headers[b'_line'][1] == b'503':
        response.set_status(503, b'Under Maintenance')
        response.set_content_type(b'text/plain')

        return b'Under Maintenance'


@app.route('/getheaderline')
async def get_headerline(**server):
    request = server['request']

    assert (b'%s?%s' % (request.path, request.query_string)) == request.url

    # b'GET /getheaderline HTTP/1.1'
    return b'%s %s HTTP/%s' % (
        request.method,
        request.url,
        request.version
    )


@app.route('/getip')
async def get_ip(**server):
    request = server['request']

    # b'127.0.0.1'
    return request.ip


@app.route('/gethost')
async def get_host(**server):
    # b'localhost:28000'
    return server['request'].host


@app.route('/getquery')
async def get_query(**server):
    request = server['request']

    assert request.query['a'] == ['111', 'xyz']
    assert request.query['b'] == ['222']

    data = []

    for name, value in request.query.items():
        data.append('%s=%s' % (name, value[0]))

    # b'a=111&b=222'
    return '&'.join(data)


@app.route(r'^/page/(?P<page_id>\d+)')
async def get_page(**server):
    # b'101'
    return server['request'].params['path'].get('page_id')


@app.route('/getcookies')
async def get_cookies(**server):
    request = server['request']

    assert request.headers.get(b'cookie') == [b'a=123', b'a=xxx, yyy']
    assert request.cookies['a'] == ['xxx, yyy', '123']

    # b'a=123, a=xxx, yyy'
    return b', '.join(request.headers.getlist(b'cookie'))


async def coro_acquire(lock):
    await lock.acquire()
    await asyncio.sleep(10)


@app.route('/getlock')
async def get_lock(**server):
    request = server['request']
    lock = server['lock']

    async with lock:
        yield b'Lock'

    async with lock(5):
        yield b' '

    request.protocol.create_task(coro_acquire(lock))

    try:
        await asyncio.sleep(0.1)
        await lock.acquire(timeout=0)
    except TimeoutError:
        yield b'was acquired!'
    finally:
        lock.release()


@app.route('/triggermemoryleak')
async def trigger_memory_leak(**server):
    if LIMIT_MEMORY == 0:
        # non-Linux
        return b''

    initial_memory_usage = memory_usage()
    data = bytearray()

    while initial_memory_usage + len(data) <= 52428800:
        data.extend(b' ' * 1048576)

    try:
        await asyncio.sleep(10)
    finally:
        data.clear()

    # b'' will be returned instead of b'OK'
    # due to the memory limit being exceeded
    return b'OK'


@app.route('/submitform')
async def post_form(**server):
    request = server['request']

    await request.form(max_size=8192)

    data = []

    for name, value in request.params['post'].items():
        data.append('%s=%s' % (name, value[0]))

    # b'user=myuser&pass=mypass'
    return '&'.join(data)


@app.route('/upload')
async def upload(request, content_type=b'application/octet-stream'):
    if request.query_string == b'maxqueue':
        request.protocol.options['max_queue_size'] = 0

    try:
        size = int(request.query['size'][0])
        yield (await request.read(0)) + (await request.read(size))
    except KeyError:
        async for data in request.stream():
            yield data

        async for data in request.stream():
            # should not raised
            raise Exception('EOF!!!')


@app.route('/upload/multipart')
async def upload_multipart(request, response, stream=False, **server):
    assert server != {}
    assert 'request' not in server
    assert 'response' not in server

    response.set_content_type(b'text/csv')

    # should be ignored
    yield b''

    yield b'name,length,type,data\r\n'

    # should be ignored
    yield b''

    # stream multipart file upload then send it back as csv
    async for part in request.files(max_files=1):
        yield b'%s,%d,%s,%s\r\n' % (part['name'].encode(),
                                    part['length'],
                                    part['type'].encode(),
                                    (part['data'][:5] + part['data'][-3:]))

    async for part in request.files(max_file_size=262144):
        if part['eof']:
            part['data'] = b'-----' + part['data'][-3:]
        else:
            part['data'] = part['data'][:5] + b'---'

        yield b'%s,%d,%s,%s\r\n' % (part['name'].encode(),
                                    part['length'],
                                    part['type'].encode(),
                                    (part['data'][:5] + part['data'][-3:]))

    async for part in request.files():
        # should not raised
        raise Exception('EOF!!!')


@app.route('/download')
async def download(request, response):
    if request.query_string == b'executor':
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            await response.sendfile(
                TEST_FILE, content_type='text/plain', executor=executor
            )
    else:
        await response.sendfile(
            TEST_FILE,
            count=os.stat(TEST_FILE).st_size + 10, content_type=b'text/plain'
        )


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


@app.route('/sse')
async def sse_handler(sse=None, **server):
    assert server != {}

    if sse.request.query_string == b'error':
        # InternalServerError due to '\n' in the event value
        await sse.send('Hello', event='hel\nlo')

    await sse.send('Hel\nlo', event='hello')
    await sse.send(b'Wor', event_id='foo')
    await sse.send(b'ld!', retry=10000)

    # await sse.response.write(b'')
    # sse.response.close(keepalive=True)
    await sse.close()


@app.route('/timeouts')
async def timeouts(request, response):
    if request.query_string == b'recv':
        # attempt to read body on a GET request
        # should raise a TimeoutError and ended up with a RequestTimeout
        await request.recv(100)
    elif request.query_string == b'handler':
        await asyncio.sleep(10)
    elif request.query_string == b'close':
        response.close()
        await asyncio.sleep(10)


@app.route('/reload')
async def reload(request, **server):
    assert server != {}
    assert 'request' not in server
    assert 'response' in server

    yield b'%d' % os.getpid()

    if request.query_string != b'':
        mtime = float(request.query_string)

        # simulate a code change
        os.utime(TEST_FILE, (mtime, mtime))

# test multiple ports
app.listen(HTTP_PORT + 1, request_timeout=1, keepalive_timeout=2,
           app_handler_timeout=2, app_close_timeout=0)
app.listen(HTTP_PORT + 2)

# test unix socket
# 'tremolo-test.sock'
app.listen('tremolo-test', debug=False, client_max_body_size=1048576)

if __name__ == '__main__':
    app.run(HTTP_HOST, port=HTTP_PORT, limit_memory=LIMIT_MEMORY,
            debug=True, reload=True,
            client_max_body_size=1048576, ws_max_payload_size=73728)

# END
