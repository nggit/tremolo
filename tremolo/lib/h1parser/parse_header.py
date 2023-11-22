# Copyright (c) 2023 nggit


class Headers(dict):
    def getlist(self, name):
        values = self.get(name, [])

        if isinstance(values, list):
            result = []

            for v in values:
                result.extend(v.replace(b', ', b',').split(b',', 100))

            return result

        return values.replace(b', ', b',').split(b',')


class ParseHeader:
    __slots__ = ('is_request',
                 'is_response',
                 'is_valid_request',
                 'is_valid_response',
                 '_data',
                 'headers',
                 '_headers',
                 '_header_size')

    def __init__(self, data=bytearray(), **kwargs):
        self.parse(data, **kwargs)

    def parse(self, data, header_size=None, excludes=[],
              max_lines=100, max_line_size=8190):
        self.is_request = False
        self.is_response = False
        self.is_valid_request = False
        self.is_valid_response = False

        self._data = data
        self.headers = Headers()
        self._headers = []
        self._header_size = header_size

        if data == b'' or not isinstance(data, (bytearray, bytes)):
            return self

        if isinstance(data, bytes):
            self._data = bytearray(data)

        if header_size is None:
            self._header_size = self._data.find(b'\r\n\r\n')

        if self._header_size == -1:
            return self

        header = self._data[:self._header_size]

        if header == b'':
            return self

        header.extend(b'\r\n')
        start = 0

        while True:
            end = header.find(b'\r\n', start)

            if end == -1:
                break

            max_lines -= 1

            if max_lines < 0 or end - start > max_line_size:
                self.is_valid_request = False
                self.is_valid_response = False

                return self

            line = header[start:end]
            colon_pos = line.find(b':', 1)

            if colon_pos > 0:
                name = line[:colon_pos]
                name_lc = bytes(name.lower())
                value = line[colon_pos + 1:]

                if value.startswith(b' '):
                    value = value[1:]

                if name_lc in self.headers and isinstance(
                        self.headers[name_lc], list):
                    self.headers[name_lc].append(value)
                else:
                    if name_lc in self.headers:
                        self.headers[name_lc] = [self.headers[name_lc], value]
                    else:
                        self.headers[name_lc] = value

                if name_lc not in excludes:
                    self._headers.append((name_lc, value))
            elif start == 0:
                if line.startswith(b'HTTP/'):
                    self.is_response = True

                    try:
                        (
                            _,
                            self.headers[b'_version'],
                            _status,
                            self.headers[b'_message']
                        ) = line.replace(b'/', b' ').split(None, 3)
                        self.headers[b'_status'] = int(_status)
                        self.is_valid_response = True
                    except ValueError:
                        self.headers[b'_version'] = b''
                        self.headers[b'_status'] = 0
                        self.headers[b'_message'] = b''
                else:
                    url_end_pos = line.find(b' HTTP/')

                    if url_end_pos > 0:
                        self.is_request = True

                        try:
                            (
                                self.headers[b'_method'],
                                self.headers[b'_url']
                            ) = line[:url_end_pos].split(b' ', 1)
                            self.headers[b'_version'] = line[url_end_pos + len(' HTTP/'):]  # noqa: E501
                            self.is_valid_request = True
                        except ValueError:
                            self.headers[b'_method'] = b''
                            self.headers[b'_url'] = b''
                            self.headers[b'_version'] = b''

                self.headers[b'_line'] = line
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

    def save(self, body=False):
        if self._header_size in (None, -1):
            return self._data

        if body:
            data = self._data[self._header_size:]
        else:
            data = self._data[self._header_size:self._header_size + 4]

        return bytearray(b'\r\n').join(
            [self.headers.get(b'_line', b'')] +
            [bytearray(b': ').join(v) for v in self._headers]
        ) + data
