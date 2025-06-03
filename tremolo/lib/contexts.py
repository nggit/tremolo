# Copyright (c) 2023 nggit


class Context:
    def __init__(self, *args, **kwargs):
        self.__dict__.update(*args, **kwargs)

    def __repr__(self):
        return self.__dict__.__repr__()

    def __getattr__(self, name):  # clear(), get(), update(), etc.
        return getattr(self.__dict__, name)

    def __setitem__(self, key, value):
        self.__setattr__(key, value)

    def __getitem__(self, key):
        return self.__dict__[key]

    def __delitem__(self, key):
        del self.__dict__[key]

    def __contains__(self, key):
        return self.__dict__.__contains__(key)


class WorkerContext(Context):
    _tasks = set()

    def __init__(self):
        self.__dict__['info'] = {}
        self.__dict__['options'] = {}

    @property
    def tasks(self):
        return self._tasks

    @property
    def info(self):
        return self.__dict__['info']

    @property
    def options(self):
        return self.__dict__['options']

    @property
    def connections(self):
        return self.__dict__.get('connections', None)

    @property
    def executor(self):
        return self.__dict__.get('executor', None)


class ConnectionContext(Context):
    __slots__ = ('_tasks',)  # won't appear in self.__dict__. safe from clear()

    def __init__(self):
        self._tasks = set()

    @property
    def tasks(self):
        return self._tasks

    @property
    def transport(self):
        return self.__dict__.get('transport', None)

    @property
    def client(self):
        if 'client' not in self.__dict__ and self.transport is not None:
            sock = self.transport.get_extra_info('socket')
            self.__dict__['client'] = sock.getpeername() or None

            if isinstance(self.__dict__['client'], tuple):
                self.__dict__['client'] = self.__dict__['client'][:2]

        return self.__dict__.get('client', None)


class RequestContext(Context):
    def __init__(self):
        self.__dict__['options'] = {}

    @property
    def options(self):
        return self.__dict__['options']
