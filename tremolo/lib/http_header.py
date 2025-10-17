# Copyright (c) 2023 nggit

from tremolo.utils import parse_fields


def is_safe(data):
    return not (b'\r' in data or b'\n' in data or 0 in data)


def iter_lines(data, limit=65536):
    start = 0

    while start < limit:
        end = data.find(b'\r\n', start, limit)

        if end == -1:
            if start < len(data):
                yield bytes(data[start:limit])

            break

        yield bytes(data[start:end])
        start = end + 2


class Headers(dict):
    def getlist(self, name, separator=b',', split=None):
        result = []

        if name in self:
            for value in self[name]:
                for v in parse_fields(value, separator, split):
                    result.append(v)

        return result


class HTTPHeader:
    __slots__ = ('is_valid', 'line', 'method', 'url', 'version', 'headers')

    def __init__(self):
        self.is_valid = False
        self.line = None
        self.method = None
        self.url = None
        self.version = None
        self.headers = None

    @property
    def is_request(self):
        return not (self.method is None or self.url is None)

    def parse(self, data, header_size=0, max_lines=100, max_line_size=8190):
        self.headers = Headers()

        if not data:
            return self

        lines = iter_lines(data, header_size or len(data))
        self.line = lines.__next__()

        if len(self.line) > max_line_size or not is_safe(self.line):
            return self

        path_end = self.line.rfind(b' HTTP/')

        if path_end > 0:
            try:
                self.method, self.url = self.line[:path_end].split(b' ', 1)
                self.version = self.line[path_end + 6:]
            except ValueError:
                self.method = b''
                self.url = b''

            if self.version in (b'1.1', b'1.0'):
                self.is_valid = True
            else:
                self.version = b'1.0'

        while max_lines > 1:
            try:
                line = lines.__next__()

                if line == b'':
                    break

                if len(line) > max_line_size or not is_safe(line):
                    self.is_valid = False
                    return self

                colon_pos = line.find(b':', 1)

                if colon_pos > 0 and line[colon_pos - 1] != 32:
                    name = line[:colon_pos].lower()
                    value = line[colon_pos + 1:].strip(b' \t')

                    if name in self.headers:
                        self.headers[name].append(value)
                    else:
                        self.headers[name] = [value]
                else:
                    self.is_valid = False
                    break
            except StopIteration:
                break

            max_lines -= 1
        else:
            self.is_valid = False

        if self.is_request:
            if b'host' in self.headers:
                if len(self.headers[b'host']) != 1:
                    self.is_valid = False
            else:
                self.headers[b'host'] = [b'']

                if self.is_valid and self.version == b'1.1':
                    self.is_valid = False

        return self

    def getheaders(self):
        return [(k, v) for k in self.headers for v in self.headers[k]]

    def gethost(self):
        values = self.headers.get(b'x-forwarded-host',
                                  self.headers.get(b'host'))
        if values:
            return values[0]
