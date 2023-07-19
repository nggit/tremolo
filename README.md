# Tremolo

Tremolo is a stream-oriented, asynchronous, programmable HTTP server written in pure Python. It can also serve as an ASGI server.

Tremolo provides a common routing functionality to some unique features such as download/upload speed limiters, etc. While maintaining its simplicity and performance.

Being built with a stream in mind, Tremolo tends to use `yield` instead of `return` in route handlers.

```python
@app.route('/hello')
async def hello_world(**server):
    yield b'Hello '
    yield b'world!'
```

You can take advantage of this to serve big files efficiently:

```python
@app.route('/my/url/big.data')
async def my_big_data(content_type='application/octet-stream', **server):
    buffer_size = server['context'].options['buffer_size']

    with open('/my/folder/big.data', 'rb') as f:
        chunk = True

        while chunk:
            chunk = f.read(buffer_size)
            yield chunk
```

And other use cases…

## Example
Here is a complete *hello world* example in case you missed the usual `return`.

```python
from tremolo import Tremolo

app = Tremolo()

@app.route('/hello')
async def hello_world(**server):
    return 'Hello world!', 'latin-1'

if __name__ == '__main__':
    app.run('0.0.0.0', 8000, debug=True)
```

Well, `latin-1` on the right side is not required. The default is `utf-8`.

You can save it as `hello.py` and just run it with `python3 hello.py`.

Your first *hello world* page with Tremolo will be at http://localhost:8000/hello.

## ASGI Server
Tremolo is an HTTP Server framework. You can build abstractions on top of it, say an ASGI server.

In fact, Tremolo already has ASGI server implementation.

So you can immediately use existing [ASGI applications / frameworks](https://asgi.readthedocs.io/en/latest/implementations.html#application-frameworks), behind Tremolo (ASGI server).

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
        'body': b'Hello world!'
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

It's also possible to run the ASGI server programmatically ([example with uvloop](https://github.com/nggit/tremolo/blob/master/example_uvloop.py)):

```
python3 example_uvloop.py
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

What's interesting is that this may become different when [CPython becomes faster](https://devblogs.microsoft.com/python/python-311-faster-cpython-team/),
or another faster Python implementation comes along.

All I can say is that Tremolo is built with simplicity in mind, so performance will naturally follow.

## Misc
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

```python
import asyncio
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
```

## Installing
Tremolo is still in the early stages of development. But you can try installing it if you like.

```
python3 -m pip install --upgrade tremolo
```

## Testing
Just run `python3 alltests.py` for all tests. Or each *test_\*.py* in the [tests/](https://github.com/nggit/tremolo/tree/master/tests) folder, for example `python3 tests/test_cli.py`.

If you also want measurements with [coverage](https://coverage.readthedocs.io/):

```
coverage run alltests.py
coverage combine
coverage report
coverage html # to generate html reports
```

## License
MIT
