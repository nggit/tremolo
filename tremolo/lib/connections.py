# Copyright (c) 2023 nggit


class KeepAliveConnections(dict):
    def __init__(self, *args, maxlen=512, **kwargs):
        if not isinstance(maxlen, int):
            raise ValueError('expected type int, got %s' %
                             type(maxlen).__name__)

        if maxlen < 1:
            raise ValueError('maxlen must be greater or equal to 1')

        self._maxlen = maxlen
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, value)

        if self.__len__() > self._maxlen:
            del self[next(self.__iter__())]
