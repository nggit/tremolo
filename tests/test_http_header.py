#!/usr/bin/env python3

import unittest
import os
import sys

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo.lib.http_header import HTTPHeader  # noqa: E402


def repr_pretty(data, indent=4, level=1):
    pad = ' ' * indent * level

    if isinstance(data, dict):
        if not data:
            return '{}'

        items = [pad + f'{repr(key)}: {repr_pretty(value, indent, level + 1)}'
                 for key, value in data.items()]

        return '{\n' + ',\n'.join(items) + '\n' + pad[indent:] + '}'

    if isinstance(data, list):
        if not data:
            return '[]'

        items = [pad + repr_pretty(item, indent, level + 1) for item in data]

        return '[\n' + ',\n'.join(items) + '\n' + pad[indent:] + ']'

    return repr(data)


class TestHTTPHeader(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.header = HTTPHeader()

    def tearDown(self):
        print(repr_pretty(self.header.headers))

    def test_empty(self):
        self.header.parse(b'')
        self.assertFalse(self.header.is_valid)
        self.assertEqual(self.header.gethost(), None)
        self.assertEqual(self.header.method, None)
        self.assertEqual(self.header.url, None)
        self.assertEqual(self.header.version, None)

    def test_break(self):
        self.header.parse(b'\r\n\r\n')
        self.assertFalse(self.header.is_valid)
        self.assertEqual(self.header.gethost(), None)
        self.assertEqual(self.header.method, None)
        self.assertEqual(self.header.url, None)
        self.assertEqual(self.header.version, None)

    def test_max_lines(self):
        self.header.parse(
            b'GET / HTTP/1.0\r\n'
            b'Host: localhost\r\n'
            b'Accept: */*\r\n\r\n', max_lines=2
        )
        self.assertFalse(self.header.is_valid)
        self.assertEqual(self.header.gethost(), b'localhost')
        self.assertEqual(self.header.method, b'GET')
        self.assertEqual(self.header.url, b'/')
        self.assertEqual(self.header.version, b'1.0')

    def test_max_line_size(self):
        self.header.parse(
            b'GET / HTTP/1.0\r\n'
            b'Host: localhost\r\n'
            b'Accept: */*\r\n\r\n', max_line_size=14
        )
        self.assertFalse(self.header.is_valid)
        self.assertEqual(self.header.gethost(), None)
        self.assertEqual(self.header.method, b'GET')
        self.assertEqual(self.header.url, b'/')
        self.assertEqual(self.header.version, b'1.0')

    def test_request_no_host_10(self):
        self.header.parse(b'GET / HTTP/1.0\r\n\r\n')
        self.assertTrue(self.header.is_valid)
        self.assertEqual(self.header.gethost(), b'')
        self.assertEqual(self.header.method, b'GET')
        self.assertEqual(self.header.url, b'/')
        self.assertEqual(self.header.version, b'1.0')

    def test_request_no_host_11(self):
        self.header.parse(
            b'GET / HTTP/1.1\r\nAccept: text/html\r\n'
            b'Accept: image/*\r\n\r\n'
        )
        self.assertFalse(self.header.is_valid)
        self.assertEqual(self.header.gethost(), b'')
        self.assertEqual(self.header.method, b'GET')
        self.assertEqual(self.header.url, b'/')
        self.assertEqual(self.header.version, b'1.1')

    def test_request_bad(self):
        self.header.parse(b' HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
        self.assertFalse(self.header.is_valid)
        self.assertEqual(self.header.gethost(), b'example.com:443')
        self.assertEqual(self.header.method, None)
        self.assertEqual(self.header.url, None)
        self.assertEqual(self.header.version, None)

    def test_request_bad_head(self):
        self.header.parse(b'HEAD HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
        self.assertFalse(self.header.is_valid)
        self.assertEqual(self.header.gethost(), b'example.com:443')
        self.assertEqual(self.header.method, b'')
        self.assertEqual(self.header.url, b'')
        self.assertEqual(self.header.version, b'1.0')

    def test_request_bad_path(self):
        self.header.parse(
            b'HEAD /Path: HTTP/1.0/ HTTP/1.1\r\n'
            b'Host: example.com:443\r\n\r\n'
        )
        self.assertTrue(self.header.is_valid)
        self.assertEqual(self.header.gethost(), b'example.com:443')
        self.assertEqual(self.header.method, b'HEAD')
        self.assertEqual(self.header.url, b'/Path: HTTP/1.0/')
        self.assertEqual(self.header.version, b'1.1')

    def test_response(self):
        self.header.parse(
            b'HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n'
            b'Connection: close\r\n\r\n200 OK\r\n'
        )
        self.assertFalse(self.header.is_valid)  # True
        self.assertEqual(self.header.gethost(), None)
        self.assertEqual(self.header.method, None)
        self.assertEqual(self.header.url, None)
        self.assertEqual(self.header.version, None)  # b'1.0'

    def test_response_bad_status(self):
        self.header.parse(
            b'HTTP/1.0 xxx Not Found\r\nContent-Type: text/plain\r\n'
            b'Connection: close\r\n\r\n404 Not Found\r\n'
        )
        self.assertFalse(self.header.is_valid)
        self.assertEqual(self.header.gethost(), None)
        self.assertEqual(self.header.method, None)
        self.assertEqual(self.header.url, None)
        self.assertEqual(self.header.version, None)  # b''


if __name__ == '__main__':
    unittest.main()
