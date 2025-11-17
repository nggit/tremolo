# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Anggit Arfanto

from urllib.parse import unquote_to_bytes as unquote


def parse_fields(data, separator=b';', split=b'=', max_fields=100):
    if len(separator) != 1:
        raise ValueError('separator must be a single one-byte character')

    end = len(data)

    while max_fields > 0:
        start = data.rfind(separator, 0, end) + 1

        if split:
            name, _, value = data[start:end].partition(split)

            if name:
                yield (name.strip().lower(), unquote(value.strip(b' \t"')))
        else:
            yield data[start:end].strip().lower()

        if start == 0:
            break

        end = start - 1
        max_fields -= 1


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
    def __init__(self):
        self.version = None
        self.status = None
        self.message = None
        self.headers = Headers()

    def parse(self, data, header_size=0, max_lines=100):
        if self.version is not None:
            return self.__class__().parse(data, header_size, max_lines)

        if not data:
            return self

        lines = iter_lines(data, header_size or len(data))
        line = lines.__next__()
        self.version, status, self.message = line.split(b' ', 2)
        self.status = int(status)

        while max_lines > 1:
            try:
                line = lines.__next__()

                if line == b'':
                    break

                colon_pos = line.find(b':', 1)

                if colon_pos > 0 and line[colon_pos - 1] != 32:
                    name = line[:colon_pos].lower()
                    value = line[colon_pos + 1:].strip(b' \t')

                    if name in self.headers:
                        self.headers[name].append(value)
                    else:
                        self.headers[name] = [value]
            except StopIteration:
                break

            max_lines -= 1

        return self

    def getheaders(self):
        return [(k, v) for k in self.headers for v in self.headers[k]]
