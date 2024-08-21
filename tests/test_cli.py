#!/usr/bin/env python3

import os
import sys
import unittest

from io import StringIO

# makes imports relative from the repo directory
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from tremolo.__main__ import usage, bind  # noqa: E402
from tremolo.utils import parse_args  # noqa: E402

STDOUT = sys.stdout


def extra(value='', **context):
    print('Extra:', value)
    context['options']['extra'] = value


def run():
    return parse_args(help=usage, bind=bind, extra=extra)


class TestCLI(unittest.TestCase):
    def setUp(self):
        try:
            sys.modules['__main__'].tests_run += 1
        except AttributeError:
            sys.modules['__main__'].tests_run = 1

        print('\r\033[2K{0:d}. {1:s}'.format(sys.modules['__main__'].tests_run,
                                             self.id()))

        self.output = StringIO()

    def tearDown(self):
        self.output.close()
        sys.argv.clear()

    def test_cli_help(self):
        sys.argv.append('--help')

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue()[:6], 'Usage:')
        self.assertEqual(code, 0)

    def test_cli_no_ws(self):
        sys.argv.append('--no-ws')

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_debug(self):
        sys.argv.append('--debug')

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_host(self):
        sys.argv.extend(['--host', 'localhost'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_port(self):
        sys.argv.extend(['--port', '8000'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_invalidport(self):
        sys.argv.extend(['--port', 'xx'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue()[:15], 'Invalid --port ')
        self.assertEqual(code, 1)

    def test_cli_bind(self):
        sys.argv.extend(['--bind', 'localhost:8000'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_bindsocket(self):
        sys.argv.extend(['--bind', '/tmp/file.sock'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_bindsocket_windows(self):
        sys.argv.extend(['--bind', r'C:\Somewhere\Temp\file.sock'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_invalidbind(self):
        sys.argv.extend(['--bind', 'localhost:xx'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue()[:15], 'Invalid --bind ')
        self.assertEqual(code, 1)

    def test_cli_sslcert(self):
        sys.argv.extend(['--ssl-cert', '/path/to/fullchain.pem'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_sslkey(self):
        sys.argv.extend(['--ssl-key', '/path/to/privkey.pem'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)

    def test_cli_extra(self):
        sys.argv.extend(['--extra', 'foo'])

        code = 0
        sys.stdout = self.output

        try:
            self.assertEqual(run()['extra'], 'foo')
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue()[:10], 'Extra: foo')
        self.assertEqual(code, 0)

    def test_cli_invalidarg(self):
        sys.argv.append('--invalid')

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue()[:31],
                         'Unrecognized option "--invalid"')
        self.assertEqual(code, 1)

    def test_cli_app(self):
        sys.argv.extend(['', 'example:app'])

        code = 0
        sys.stdout = self.output

        try:
            run()
        except SystemExit as exc:
            if exc.code:
                code = exc.code

        sys.stdout = STDOUT

        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(code, 0)


if __name__ == '__main__':
    unittest.main()
