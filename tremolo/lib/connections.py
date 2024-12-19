# Copyright (c) 2023 nggit


class KeepAliveConnections(dict):
    def __init__(self, maxlen=512):
        if not isinstance(maxlen, int) or maxlen < 1:
            raise ValueError(
                'maxlen must be an integer greater than or equal to 1, '
                'got %s' % repr(maxlen)
            )

        self._maxlen = maxlen

    def __repr__(self):
        return self.keys().__repr__()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)

        if self.__len__() > self._maxlen:
            del self[self.__iter__().__next__()]

    def add(self, item):
        self[item] = None

    def discard(self, item):
        self.pop(item, None)
