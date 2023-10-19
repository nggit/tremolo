#!/usr/bin/env python3

import os
import socket
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from tremolo import Tremolo  # noqa: E402
from tremolo.exceptions import BadRequest  # noqa: E402
from tremolo.lib.__queue import Queue  # noqa: E402
from tremolo.lib.connections import KeepAliveConnections  # noqa: E402
from tremolo.lib.contexts import ServerContext  # noqa: E402
from tremolo.lib.pools import Pool, QueuePool  # noqa: E402
from tests import handlers, middlewares  # noqa: E402
from tests.http_server import HTTP_PORT  # noqa: E402
from tests.utils import function, logger  # noqa: E402

app = Tremolo()


class TestTremoloObjects(unittest.TestCase):
    def setUp(self):
        try:
            sys.modules['__main__'].tests_run += 1
        except AttributeError:
            sys.modules['__main__'].tests_run = 1

        print('\r\033[2K{0:d}. {1:s}'.format(sys.modules['__main__'].tests_run,
                                             self.id()))

    def test_000run_host_none(self):
        with self.assertRaises(ValueError):
            # app.run(host=None)
            app.run()

    def test_listen(self):
        self.assertTrue(app.listen(8000))
        self.assertFalse(app.listen(8000))
        self.assertTrue(app.listen(8001, host='localhost'))
        self.assertTrue(app.listen(8002, reuse_port=True, worker_num=2))

    def test_route(self):
        app.route('/hello')(handlers.hello)
        pattern, func, options = app.routes[b'2#hello'][-1]

        self.assertEqual(pattern, b'^/+hello(?:/+)?(?:\\?.*)?$')
        self.assertEqual(func(), b'Hello!')
        self.assertEqual(options, {})

        app.route('/hello/world')(handlers.hello_world)
        pattern, func, options = app.routes[b'3#hello'][-1]

        self.assertEqual(pattern, b'^/+hello/world(?:/+)?(?:\\?.*)?$')
        self.assertEqual(func(), b'Hello, World!')
        self.assertEqual(options, {'a': 1, 'b': 2})

        app.route('/hello/python')(handlers.hello_python)
        pattern, func, options = app.routes[b'3#hello'][-1]

        self.assertEqual(pattern, b'^/+hello/python(?:/+)?(?:\\?.*)?$')
        self.assertEqual(func(), b'Hello, Python!')
        self.assertEqual(options, {})

    def test_route_index(self):
        app.route('/')(handlers.index)
        pattern, func, options = app.routes[1][-1]

        self.assertEqual(pattern, b'^/+(?:\\?.*)?$')
        self.assertEqual(func(), b'Index!')
        self.assertEqual(options, {})

    def test_route_regex(self):
        app.route(r'^/page/(?P<page_id>\d+)')(handlers.my_page)
        pattern, func, options = app.routes[-1][-1]

        self.assertEqual(pattern, b'^/page/(?P<page_id>\\d+)')
        self.assertEqual(func(), b'My Page!')
        self.assertEqual(options, {})

        app.compile_routes(app.routes)
        pattern, func, options = app.routes[-1][-1]

        self.assertEqual(pattern.pattern, b'^/page/(?P<page_id>\\d+)')
        self.assertEqual(func(), b'My Page!')
        self.assertEqual(options, {})

    def test_route_error(self):
        app.route(404)(handlers.error_404)

        for code, func, options in app.routes[0]:
            if code == 404:
                self.assertEqual(func(), b'Not Found!!!')
                self.assertEqual(options['status'], (404, b'Not Found'))
                break
        else:
            self.fail('route does not exist!')

    def test_middleware(self):
        for attr_name in dir(middlewares):
            if not attr_name.startswith('on_'):
                continue

            getattr(app, attr_name)(getattr(middlewares, attr_name))
            func, options = app.middlewares[attr_name[len('on_'):]][-1]

            self.assertEqual(func(), b'Halt!')
            self.assertEqual(options, {})

            getattr(app, attr_name)()(getattr(middlewares, attr_name))
            func, options = app.middlewares[attr_name[len('on_'):]][-1]

            self.assertEqual(func(), b'Halt!')
            self.assertEqual(options, {})

    @function
    async def test_handler(self):
        for handler in app.routes[1]:
            self.assertEqual(await handler[1](), b'Service Unavailable')

        for handler in app.routes[0]:
            if handler[0] == 400:
                with self.assertRaises(BadRequest):
                    await handler[1]()

            elif handler[0] == 404:
                context = ServerContext()

                self.assertEqual(repr(context), repr(context.__dict__))

                context.set('options', {'server_info': {'name': b'Tremolo'}})
                context.protocol = context
                context.path = b'/invalid">url'

                data = bytearray()

                async for buf in handler[1](request=context):
                    data.extend(buf)

                self.assertTrue(data[:15] == b'<!DOCTYPE html>')
                self.assertTrue(data[-7:] == b'</html>')
                self.assertTrue(b'/invalid&quot;&gt;url' in data)
                self.assertTrue(b'>Tremolo</address>' in data)

    def test_create_sock(self):
        # simulate unsupported IPv6
        del socket.AF_INET6

        with app.create_sock('localhost', HTTP_PORT + 3) as sock:
            self.assertEqual(sock.getsockname()[:2][-1], HTTP_PORT + 3)

        # trigger sock file already exists
        if not os.path.exists('tremolo.sock'):
            open('tremolo.sock', 'a').close()

        for sock_name, sock_file in (('tremolo_sock', 'tremolo_sock.sock'),
                                     ('tremolo.sock', 'tremolo.sock')):
            with app.create_sock(sock_name, HTTP_PORT + 3) as sock:
                if sock.family.name == 'AF_UNIX':
                    self.assertEqual(sock.getsockname(), sock_file)
                else:
                    self.assertEqual(sock.getsockname()[1], HTTP_PORT + 3)

    def test_queue_pool(self):
        pool = Pool(0, logger)
        queue = QueuePool(0, logger)

        self.assertEqual(pool.create(), None)
        self.assertEqual(len(queue.get()), 2)
        self.assertEqual(queue.get()[0].__class__, Queue)
        self.assertEqual(queue.get()[1].__class__, Queue)

    def test_serverconnections(self):
        with self.assertRaises(ValueError):
            _ = KeepAliveConnections(maxlen=-10)

        with self.assertRaises(ValueError):
            _ = KeepAliveConnections(maxlen=0)

        with self.assertRaises(ValueError):
            _ = KeepAliveConnections(maxlen=(0, 1))

        conn = KeepAliveConnections(maxlen=2)
        conn['a'] = 1
        conn['b'] = 2
        conn['c'] = 3

        self.assertEqual(list(conn.values()), [2, 3])


if __name__ == '__main__':
    unittest.main()
