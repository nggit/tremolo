# Copyright (c) 2023 nggit

class Headers(dict):
    def getlist(self, name):
        values = self.get(name, [])

        if isinstance(values, list):
            result = []

            for v in values:
                result.extend(v.replace(b', ', b',').split(b','))

            return result

        return values.replace(b', ', b',').split(b',')

class ParseHeader:
    def __init__(self, data=bytearray(), **kwargs):
        self.parse(data, **kwargs)

    def parse(self, data=bytearray(), excludes=[]):
        self.is_request = False
        self.is_response = False
        self.is_valid_request = False
        self.is_valid_response = False
        self._headers = Headers()
        self._header = {}
        self._body = bytearray()

        if data == b'' or not isinstance(data, (bytearray, bytes)):
            return self

        if isinstance(data, bytes):
            data = bytearray(data)

        end = data.find(b'\r\n\r\n')

        if end == -1:
            return self

        self._body = data[end:]
        data = data[:end]

        if data == b'':
            return self

        data.extend(b'\r\n')
        start = 0

        while True:
            end = data.find(b'\r\n', start)

            if end == -1:
                break

            line = data[start:end]
            colon_pos = line.find(b':', 1)

            if colon_pos > 0:
                name = line[:colon_pos]
                name_lc = bytes(name.lower())
                value = line[colon_pos + 1:]

                if value.startswith(b' '):
                    value = value[1:]

                if name_lc in self._headers and isinstance(self._headers[name_lc], list):
                    self._headers[name_lc].append(value)
                else:
                    if name_lc in self._headers:
                        self._headers[name_lc] = [self._headers[name_lc], value]
                    else:
                        self._headers[name_lc] = value

                if name_lc not in excludes:
                    if name_lc in self._header and isinstance(self._header[name_lc], list):
                        self._header[name_lc].append(name + b': ' + value)
                    else:
                        self._header[name_lc] = [name + b': ' + value]
            else:
                if line.startswith(b'HTTP/'):
                    self.is_response = True

                    try:
                        _, self._headers[b'_version'], _status, self._headers[b'_message'] = line.replace(b'/', b' ').split(None, 3)
                        self._headers[b'_status'] = int(_status)
                        self.is_valid_response = True
                    except ValueError:
                        self._headers[b'_version'] = b''
                        self._headers[b'_status'] = 0
                        self._headers[b'_message'] = b''
                else:
                    path_end_pos = line.find(b' HTTP/')

                    if path_end_pos > 0:
                        self.is_request = True

                        try:
                            self._headers[b'_method'], self._headers[b'_path'] = line[:path_end_pos].split(b' ', 1)
                            self._headers[b'_version'] = line[path_end_pos + len(' HTTP/'):]
                            self.is_valid_request = True
                        except ValueError:
                            self._headers[b'_method'] = b''
                            self._headers[b'_path'] = b''
                            self._headers[b'_version'] = b''

                self._header[0] = [line]

            start = end + 2

        if self.is_valid_request and self._headers[b'_version'] == b'1.1' and b'host' not in self._headers:
            self._headers[b'host'] = b''
            self.is_valid_request = False

        return self

    def remove(self, remove=[]):
        if remove == [] or not isinstance(remove, list):
            return self

        for value in remove:
            if value in self._header:
                del self._header[value]

    def append(self, append={}):
        if append == {} or not isinstance(append, dict):
            return self

        for name in append:
            name_lc = name.lower()

            if name_lc in self._header and isinstance(self._header[name_lc], list):
                self._header[name_lc].append(name + b': ' + append[name])
            else:
                self._header[name_lc] = [name + b': ' + append[name]]

    def getheaders(self):
        return self._headers

    def gethost(self):
        return self._headers.get(b'x-forwarded-host', self._headers.get(b'host'))

    def getmethod(self):
        return self._headers.get(b'_method')

    def getpath(self):
        return self._headers.get(b'_path')

    def getversion(self):
        return self._headers.get(b'_version')

    def getstatus(self):
        return self._headers.get(b'_status')

    def getmessage(self):
        return self._headers.get(b'_message')

    def save(self):
        return bytearray(b'\r\n').join([bytearray(b'\r\n').join(v) for v in self._header.values()]) + self._body
