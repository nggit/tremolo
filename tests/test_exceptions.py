#!/usr/bin/env python3

import os
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo.exceptions import (  # noqa: E402
    HTTPException,
    Forbidden,
    InternalServerError,
    MethodNotAllowed,
    RequestTimeout,
    WebSocketServerClosed
)


class TestExceptions(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

    def test_from_valueerror(self):
        a = ValueError('foo')
        b = HTTPException(cause=a)

        self.assertEqual(b.__class__, InternalServerError)
        self.assertEqual(b.__cause__, a)
        self.assertEqual(b.args, ('foo',))

    def test_from_valueerror_override_args(self):
        a = ValueError('foo')
        b = HTTPException('bar', cause=a)

        self.assertEqual(b.__class__, InternalServerError)
        self.assertEqual(b.__cause__, a)
        self.assertEqual(b.args, ('bar',))

    def test_from_timeouterror(self):
        a = TimeoutError('foo')
        b = HTTPException(cause=a)

        self.assertEqual(b.__class__, RequestTimeout)
        self.assertEqual(b.__cause__, a)
        self.assertEqual(b.args, ('foo',))

    def test_from_requesttimeout_override_args(self):
        a = RequestTimeout('foo')
        b = RequestTimeout('bar', cause=a)

        self.assertTrue(b is a)
        self.assertEqual(b.__class__, RequestTimeout)
        self.assertEqual(b.__cause__, None)
        self.assertEqual(b.args, ('bar',))

    def test_from_methodnotallowed(self):
        a = MethodNotAllowed('foo', methods=(b'GET',))
        b = HTTPException(cause=a)

        self.assertTrue(b is a)
        self.assertEqual(b.__class__, MethodNotAllowed)
        self.assertEqual(b.__cause__, None)
        self.assertEqual(b.args, ('foo',))
        self.assertEqual(b.methods, (b'GET',))

    def test_from_methodnotallowed_override_args_methods(self):
        a = MethodNotAllowed('foo', methods=(b'GET',))
        b = HTTPException('bar', cause=a, methods=(b'POST',))

        self.assertTrue(b is a)
        self.assertEqual(b.__class__, MethodNotAllowed)
        self.assertEqual(b.__cause__, None)
        self.assertEqual(b.args, ('bar',))
        self.assertEqual(b.methods, (b'POST',))

    def test_to_forbidden(self):
        a = ValueError('foo')
        b = Forbidden(cause=a)

        self.assertEqual(b.__class__, Forbidden)
        self.assertEqual(b.__cause__, a)
        self.assertEqual(b.args, ('foo',))

    def test_to_forbidden_override_args(self):
        a = ValueError('foo')
        b = Forbidden('bar', cause=a)

        self.assertEqual(b.__class__, Forbidden)
        self.assertEqual(b.__cause__, a)
        self.assertEqual(b.args, ('bar',))

    def test_to_websocketserverclosed(self):
        a = ValueError('foo')
        b = WebSocketServerClosed(cause=a)

        self.assertEqual(b.__class__, WebSocketServerClosed)
        self.assertEqual(b.__cause__, a)
        self.assertEqual(b.args, ('foo',))

    def test_to_websocketserverclosed_from_forbidden_override_args(self):
        a = Forbidden('foo')
        b = WebSocketServerClosed('bar', cause=a)

        self.assertEqual(b.__class__, WebSocketServerClosed)
        self.assertEqual(b.__cause__, a)
        self.assertEqual(b.args, ('bar',))


if __name__ == '__main__':
    unittest.main()
