import asyncio
import json
from tremolo import Application

app = Application()

@app.route('/')
async def index(**server):
    html = '''
    <body>
        <p>The password is 'tremolo'</p>
        <form method="post" action="login" id="form">
            <label for="password">Enter password:</label>
            <input name="password" type="password" />
            <button>Login</button>
        </form>
        <script>
        const form = document.querySelector('#form') 
        form.addEventListener('submit', (e) => {
            e.preventDefault()
            const data = {
                password: form.querySelector('input').value
            }
            form.reset()
            fetch('/login', {
                method: "POST",
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: JSON.stringify(data)
            })
        })

        const events = new EventSource('/notifications')
        events.addEventListener('notify', (e) => {
            const data = JSON.parse(e.data)
            const n = document.createElement('div')
            n.innerHTML = `${data.text}`
            n.classList.add('notification')
            n.classList.add(data.class)
            document.body.insertBefore(n, form)

            setTimeout(() => n.classList.add('faded'), 1500)
            setTimeout(() => n.remove(), 2000)

        })
        </script>
        <style>
        .notification {
            position: absolute;
            bottom: 1em;
            right: 1em;
            color: white;
            padding: 0.5em;
            background: green;
            box-shadow: 0.1em 0.1em 0.5em grey;
        }

        .notification.message {
            background: green;
        }

        .notification.error {
            background: red;
        }

        .faded {
            opacity: 0;
            animation: fade 0.4s;
        }

        @keyframes fade {
            0% {
                opacity: 1;
            }

            100% {
                opacity: 0;
            }
        }
        </style>
    </body>
    '''

    yield html.encode()

listeners = set()

@app.route('/notifications$')
async def notify(sse=None, **server):
    if sse:
        msg = { 'text': 'listening', 'class': 'message' }
        await sse.send(json.dumps(msg).encode(), event='notify')

        queue = asyncio.Queue(maxsize=1)
        listeners.add(queue)

        try:
            while True:
                ev, data = await queue.get()
                await sse.send(json.dumps(data).encode(), event=ev)
        finally:  # the client has gone, clean up
            listeners.discard(queue)


@app.route('login$')
async def login(request):
    data = await request.body()
    data = json.loads(data.decode())

    # Not retrieving form data correctly.
    password = data.get('password') or "not working"

    if password == "tremolo":
        notification = {'text': 'correct password', 'class': 'message'}
    else:
        notification = {'text': 'incorrect password', 'class': 'error'}

    for queue in listeners:
        queue.put_nowait(['notify', notification])

    return f'ping to {len(listeners)} listeners'

if __name__ == "__main__":
    app.run('0.0.0.0', 8001, debug=True)







