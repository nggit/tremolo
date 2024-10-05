# Copyright (c) 2023 nggit


class Headers(dict):
    def copy(self):
        return self.__class__(self)

    def getlist(self, name):
        values = self.get(name, [])

        if isinstance(values, list):
            result = []

            for v in values:
                result.extend(v.replace(b', ', b',').split(b',', 100))

            return result

        return values.replace(b', ', b',').split(b',', 100)


class ParseHeader:
    __slots__ = ('is_request',
                 'is_response',
                 'is_valid_request',
                 'is_valid_response',
                 'headers',
                 '_headers',
                 '_body')

    def __init__(self, data=None, **kwargs):
        self.is_request = False
        self.is_response = False
        self.is_valid_request = False
        self.is_valid_response = False

        self.headers = Headers()
        self._headers = []
        self._body = b''

        self.parse(data, **kwargs)

    def parse(self, data, header_size=-1, header_max_size=65536, excludes=(),
              max_lines=100, max_line_size=8190):
        if data is None:
            return self

        if header_size == -1:
            header_size = data.find(b'\r\n\r\n', 0, header_max_size) + 2

        if header_size < 2:
            return self

        self.is_request = False
        self.is_response = False
        self.is_valid_request = False
        self.is_valid_response = False

        self.headers.clear()
        self._headers.clear()
        self._body = data[header_size + 2:]
        start = 0

        while True:
            end = data.find(b'\r\n', start, header_size)

            if end == -1:
                break

            max_lines -= 1
            line = bytes(data[start:end])

            if max_lines < 0 or end - start > max_line_size or b'\n' in line:
                self.is_valid_request = False
                self.is_valid_response = False
                return self

            colon_pos = line.find(b':', 1)

            if start == 0:
                http_pos = line.rfind(b'HTTP/')

                if http_pos == 0:
                    self.is_response = True

                    try:
                        (
                            _,
                            self.headers[b'_version'],
                            _status,
                            self.headers[b'_message']
                        ) = line.replace(b'/', b' ').split(b' ', 3)
                        self.headers[b'_status'] = int(_status)
                        self.is_valid_response = True
                    except ValueError:
                        self.headers[b'_version'] = b''
                        self.headers[b'_status'] = 0
                        self.headers[b'_message'] = b''
                elif http_pos > 1 and line[http_pos - 1] == 32:
                    self.is_request = True

                    try:
                        (
                            self.headers[b'_method'],
                            self.headers[b'_url']
                        ) = line[:http_pos - 1].split(b' ', 1)
                        self.headers[b'_version'] = line[http_pos + 5:]
                        self.is_valid_request = True
                    except ValueError:
                        self.headers[b'_method'] = b''
                        self.headers[b'_url'] = b''
                        self.headers[b'_version'] = b''

                self.headers[b'_line'] = line
            elif colon_pos > 0 and line[colon_pos - 1] != 32:
                name = line[:colon_pos].lower()
                value = line[colon_pos + 1:]

                if value.startswith(b' '):
                    value = value[1:]

                if (name in self.headers and
                        isinstance(self.headers[name], list)):
                    self.headers[name].append(value)
                else:
                    if name in self.headers:
                        self.headers[name] = [self.headers[name], value]
                    else:
                        self.headers[name] = value

                if name not in excludes:
                    self._headers.append((name, value))
            else:
                self.is_valid_request = False
                self.is_valid_response = False
                break

            start = end + 2

        if self.is_request and b'host' not in self.headers:
            self.headers[b'host'] = b''

            if self.is_valid_request and self.headers[b'_version'] == b'1.1':
                self.is_valid_request = False

        return self

    def remove(self, *args):
        if not args:
            return self

        i = len(self._headers)

        while i > 0:
            i -= 1

            if self._headers[i][0] in args:
                del self._headers[i]

        return self

    def append(self, *args):
        for v in args:
            if isinstance(v, tuple):
                self._headers.append(v)

        return self

    def getheaders(self):
        return self._headers

    def gethost(self):
        return self.headers.get(b'x-forwarded-host', self.headers.get(b'host'))

    def getmethod(self):
        return self.headers.get(b'_method')

    def geturl(self):
        return self.headers.get(b'_url')

    def getversion(self):
        return self.headers.get(b'_version')

    def getstatus(self):
        return self.headers.get(b'_status')

    def getmessage(self):
        return self.headers.get(b'_message')

    def save(self):
        return b'\r\n'.join(
            [self.headers.get(b'_line', b'')] +
            [b': '.join(v) for v in self._headers]
        ) + b'\r\n\r\n' + self._body
