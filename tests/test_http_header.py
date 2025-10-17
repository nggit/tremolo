#!/usr/bin/env python3

import unittest
import json
import os
import sys

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo.lib.http_header import HTTPHeader  # noqa: E402


def decode_dict(data, encoding='latin-1'):
    if isinstance(data, dict):
        return {
            key.decode(encoding): decode_dict(
                value, encoding) for key, value in data.items()
        }

    if isinstance(data, list):
        return [decode_dict(item, encoding) for item in data]

    if type(data) in (bytearray, bytes):
        return data.decode(encoding)

    return data


class TestHTTPHeader(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.obj = HTTPHeader()

    def tearDown(self):
        print(
            json.dumps(decode_dict(self.obj.headers), sort_keys=True, indent=4)
        )

    def test_empty(self):
        self.obj.parse(b'')
        self.assertFalse(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), None)
        self.assertEqual(self.obj.method, None)
        self.assertEqual(self.obj.url, None)
        self.assertEqual(self.obj.version, None)

    def test_break(self):
        self.obj.parse(b'\r\n\r\n')
        self.assertFalse(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), None)
        self.assertEqual(self.obj.method, None)
        self.assertEqual(self.obj.url, None)
        self.assertEqual(self.obj.version, None)

    def test_max_lines(self):
        self.obj.parse(
            b'GET / HTTP/1.0\r\n'
            b'Host: localhost\r\n'
            b'Accept: */*\r\n\r\n', max_lines=2
        )
        self.assertFalse(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), b'localhost')
        self.assertEqual(self.obj.method, b'GET')
        self.assertEqual(self.obj.url, b'/')
        self.assertEqual(self.obj.version, b'1.0')

    def test_max_line_size(self):
        self.obj.parse(
            b'GET / HTTP/1.0\r\n'
            b'Host: localhost\r\n'
            b'Accept: */*\r\n\r\n', max_line_size=14
        )
        self.assertFalse(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), None)
        self.assertEqual(self.obj.method, b'GET')
        self.assertEqual(self.obj.url, b'/')
        self.assertEqual(self.obj.version, b'1.0')

    def test_request_no_host_10(self):
        self.obj.parse(b'GET / HTTP/1.0\r\n\r\n')
        self.assertTrue(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), b'')
        self.assertEqual(self.obj.method, b'GET')
        self.assertEqual(self.obj.url, b'/')
        self.assertEqual(self.obj.version, b'1.0')

    def test_request_no_host_11(self):
        self.obj.parse(
            b'GET / HTTP/1.1\r\nAccept: text/html\r\n'
            b'Accept: image/*\r\n\r\n'
        )
        self.assertFalse(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), b'')
        self.assertEqual(self.obj.method, b'GET')
        self.assertEqual(self.obj.url, b'/')
        self.assertEqual(self.obj.version, b'1.1')

    def test_request_bad(self):
        self.obj.parse(b' HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
        self.assertFalse(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), b'example.com:443')
        self.assertEqual(self.obj.method, None)
        self.assertEqual(self.obj.url, None)
        self.assertEqual(self.obj.version, None)

    def test_request_bad_head(self):
        self.obj.parse(b'HEAD HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
        self.assertFalse(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), b'example.com:443')
        self.assertEqual(self.obj.method, b'')
        self.assertEqual(self.obj.url, b'')
        self.assertEqual(self.obj.version, b'1.0')

    def test_request_bad_path(self):
        self.obj.parse(
            b'HEAD /Path: HTTP/1.0/ HTTP/1.1\r\n'
            b'Host: example.com:443\r\n\r\n'
        )
        self.assertTrue(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), b'example.com:443')
        self.assertEqual(self.obj.method, b'HEAD')
        self.assertEqual(self.obj.url, b'/Path: HTTP/1.0/')
        self.assertEqual(self.obj.version, b'1.1')

    def test_response(self):
        self.obj.parse(
            b'HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n'
            b'Connection: close\r\n\r\n200 OK\r\n'
        )
        self.assertFalse(self.obj.is_valid)  # True
        self.assertEqual(self.obj.gethost(), None)
        self.assertEqual(self.obj.method, None)
        self.assertEqual(self.obj.url, None)
        self.assertEqual(self.obj.version, None)  # b'1.0'

    def test_response_bad_status(self):
        self.obj.parse(
            b'HTTP/1.0 xxx Not Found\r\nContent-Type: text/plain\r\n'
            b'Connection: close\r\n\r\n404 Not Found\r\n'
        )
        self.assertFalse(self.obj.is_valid)
        self.assertEqual(self.obj.gethost(), None)
        self.assertEqual(self.obj.method, None)
        self.assertEqual(self.obj.url, None)
        self.assertEqual(self.obj.version, None)  # b''


if __name__ == '__main__':
    unittest.main()
