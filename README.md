# Tremolo

Tremolo is a stream-oriented, asynchronous web server/framework written in pure Python. Tremolo provides a common routing functionality to some unique features such as download/upload speed limiters, etc. While maintaining its simplicity and performance.

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

## License
MIT
