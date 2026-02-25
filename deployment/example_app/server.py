
import os

from tremolo import Application

DEV_MODE = os.getuid() < 10000

app = Application()


@app.route('/')
async def hello_world(**server):
    return 'Hello, World!'


if __name__ == '__main__':
    app.run('0.0.0.0', 8080, debug=DEV_MODE, reload=DEV_MODE)
