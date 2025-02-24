# Copyright (c) 2023 nggit


class Context:
    def __init__(self):
        self.__dict__ = {}

    def __repr__(self):
        return self.__dict__.__repr__()

    def clear(self):
        self.__dict__.clear()

    def get(self, key, default=None):
        return self.__dict__.get(key, default)

    def update(self, *args, **kwargs):
        return self.__dict__.update(*args, **kwargs)

    def __setitem__(self, *args):
        self.__setattr__(*args)

    def __getitem__(self, name):
        return self.__dict__[name]

    def __contains__(self, name):
        return self.__dict__.__contains__(name)


class WorkerContext(Context):
    _tasks = set()

    def __init__(self):
        self.__dict__ = {
            'info': {},
            'options': {},
            'queues': {}
        }

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
    def queues(self):
        return self.__dict__['queues']

    @property
    def connections(self):
        return self.__dict__.get('connections', None)


class ConnectionContext(Context):
    __slots__ = ('_tasks',)

    def __init__(self):
        self.__dict__ = {}
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
        self.__dict__ = {
            'options': {}
        }

    @property
    def options(self):
        return self.__dict__['options']
