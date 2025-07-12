![Tremolo](https://raw.githubusercontent.com/nggit/tremolo/main/media/tremolo.png)
---

[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=nggit_tremolo&metric=coverage)](https://sonarcloud.io/summary/new_code?id=nggit_tremolo)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=nggit_tremolo&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=nggit_tremolo)

Tremolo is a [stream-oriented](https://nggit.github.io/tremolo-docs/basics/yield.html), asynchronous, programmable HTTP server written in pure Python. It can also serve as an [ASGI server](#asgi-server).

Tremolo provides a common routing functionality to some unique features such as download/upload speed limiters, etc. While maintaining its simplicity and performance.

Being built with a stream in mind, Tremolo tends to use `yield` instead of `return` in route handlers.

```python
@app.route('/hello')
async def hello_world(**server):
    yield b'Hello '
    yield b'world!'
```

You can take advantage of this to serve/generate big files efficiently:

```python
@app.route('/my/url/speedtest.bin')
async def my_big_data(request, response):
    buffer_size = 16384

    response.set_content_type('application/octet-stream')

    with open('/dev/random', 'rb') as f:
        chunk = True

        while chunk:
            chunk = f.read(buffer_size)
            yield chunk
```

And other use cases…

## Features
Tremolo is only suitable for those who value [minimalism](https://en.wikipedia.org/wiki/Minimalism_%28computing%29) and stability over features.

With only **3k** lines of code, with **no dependencies** other than the [Python Standard Library](https://docs.python.org/3/library/index.html), it gives you:

* A production-ready HTTP/1.x server rather than just a development server,
* of course with [WebSocket support](https://nggit.github.io/tremolo-docs/reference/websocket/)
* Keep-Alive connections with [configurable limit](https://nggit.github.io/tremolo-docs/configuration.html#keepalive_connections)
* Stream chunked uploads
* [Stream multipart uploads](https://nggit.github.io/tremolo-docs/basics/body.html#multipart) with [per-part streaming](https://github.com/nggit/tremolo/pull/293)
* Download/upload speed throttling
* [Resumable downloads](https://nggit.github.io/tremolo-docs/how-to/resumable-downloads.html)
* Framework features; routing, [CBV](https://nggit.github.io/tremolo-docs/basics/routing.html#class-based-views), async/[sync handlers](https://nggit.github.io/tremolo-docs/basics/handlers.html#synchronous-handlers), middleware, etc.
* ASGI server implementation
* PyPy compatible

All built-in in a single, portable folder module [tremolo](https://github.com/nggit/tremolo/tree/main/tremolo),
in a very compact way like a Swiss Army knife.

## Installation
```
python3 -m pip install --upgrade tremolo
```

## Example
Here is a complete *hello world* example in case you missed the usual `return`.

```python
from tremolo import Application

app = Application()

@app.route('/hello')
async def hello_world(**server):
    return 'Hello world!', 'latin-1'


if __name__ == '__main__':
    app.run('0.0.0.0', 8000, debug=True)
```

Well, `latin-1` on the right side is not required. The default is `utf-8`.

You can save it as `hello.py` and just run it with `python3 hello.py`.
And your first *hello world* page with Tremolo will be at http://localhost:8000/hello.

## ASGI Server
Tremolo is an HTTP Server framework. You can build abstractions on top of it, say an ASGI server.

In fact, Tremolo already has ASGI server (plus WebSocket) implementation.
So you can immediately use existing [ASGI applications / frameworks](https://asgi.readthedocs.io/en/latest/implementations.html#application-frameworks), on top of Tremolo (ASGI server).

For example, If a minimal ASGI application with the name `example.py`:

```python
async def app(scope, receive, send):
    assert scope['type'] == 'http'

    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [
            (b'content-type', b'text/plain')
        ]
    })
    await send({
        'type': 'http.response.body',
        'body': b'Hello, World!'
    })
```

Then you can run as follows:

```
python3 -m tremolo --debug --bind 127.0.0.1:8000 example:app
```

To see more available options:

```
python3 -m tremolo --help
```

It's also possible to run the ASGI server programmatically ([example with uvloop](https://github.com/nggit/tremolo/blob/main/example_uvloop.py)):

```
python3 example_uvloop.py
```

## Experimental Features
Experimental features can be enabled with `experimental=True` or `--experimental`.
Since they require user awareness, they are not enabled by default.

For example, even in ASGI server mode, Tremolo gives apps direct access to the server objects.
Which means that even if you use an app/framework like Starlette/FastAPI,
you can still use Tremolo's `request` and `response` objects for more optimized [streaming features](https://nggit.github.io/tremolo-docs/basics/body.html#multipart).
```python
from starlette.applications import Starlette
from starlette.routing import Route


async def homepage(request):
    # Tremolo's `request` and `response` objects
    req = request.state.server['request']
    res = request.state.server['response']

    async for data in req.stream():
        await res.write(data)

    await res.end()


routes = [
    Route('/', homepage, methods=['GET', 'POST']),
]

app = Starlette(routes=routes)
```

## Testing
Just run `python3 alltests.py` for all tests. Or individual *test_\*.py* in the [tests/](https://github.com/nggit/tremolo/tree/main/tests) folder, for example `python3 tests/test_cli.py`.

If you also want measurements with [coverage](https://coverage.readthedocs.io/):

```
coverage run alltests.py
coverage combine
coverage report
coverage html # to generate html reports
```

## Benchmarking
The first thing to note is that Tremolo is a pure Python server framework.

As a pure Python server framework, it is hard to find a comparison.
Because most servers/frameworks today are full of steroids like `httptools`, `uvloop`, Rust, etc.

You can try comparing with [Uvicorn](https://www.uvicorn.org/) with the following option (disabling steroids to be fair):

```
uvicorn --loop asyncio --http h11 --log-level error example:app
```

vs

```
python3 -m tremolo --log-level ERROR example:app
```

You will find that Tremolo is reasonably fast.

If it's not, it could be due to [--upload-rate](https://nggit.github.io/tremolo-docs/configuration.html#upload_rate) or [--download-rate](https://nggit.github.io/tremolo-docs/configuration.html#download_rate) limits, which take effect when the payload is slightly larger.
Despite causing benchmarks to show poor results, it prevents any single client from monopolizing bandwidth, ensuring responsiveness under heavy load.

However, it should be noted that bottlenecks often occur on the application side.
Which means that in real-world usage, throughput reflects more on the application than the server.

## Misc.
Tremolo utilizes `SO_REUSEPORT` (Linux 3.9+) to load balance worker processes.

```python
app.run('0.0.0.0', 8000, worker_num=2)
```

Tremolo can also listen to multiple ports in case you are using an external load balancer like Nginx / HAProxy.

```python
app.listen(8001)
app.listen(8002)

app.run('0.0.0.0', 8000)
```

You can even get higher concurrency with [PyPy](https://www.pypy.org/) or [uvloop](https://magic.io/blog/uvloop-blazing-fast-python-networking/):

```
python3 -m tremolo --loop uvloop --log-level ERROR example:app
```

See: [--loop](https://nggit.github.io/tremolo-docs/configuration.html#loop)

## License
MIT License
