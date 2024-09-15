#!/usr/bin/env python3

from tremolo import Tremolo

app = Tremolo()


@app.route('/hello')
async def hello_world(**server):
    return 'Hello world!', 'latin-1'


if __name__ == '__main__':
    app.run('0.0.0.0', 8000, debug=True, reload=True)
