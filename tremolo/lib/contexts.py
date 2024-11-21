# Copyright (c) 2023 nggit


class Context:
    def __init__(self):
        self.__dict__ = {}

    def __repr__(self):
        return self.__dict__.__repr__()

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
    def __init__(self):
        self.__dict__ = {
            'options': {},
            'queues': {},
            'tasks': set()
        }

    @property
    def options(self):
        return self.__dict__['options']

    @property
    def queues(self):
        return self.__dict__['queues']

    @property
    def tasks(self):
        return self.__dict__['tasks']


class ConnectionContext(Context):
    def __init__(self):
        self.__dict__ = {
            'transport': None,
            'socket': None,
            'tasks': set()
        }

    @property
    def transport(self):
        return self.__dict__['transport']

    @property
    def socket(self):
        if not self.__dict__['socket'] and self.transport is not None:
            self.__dict__['socket'] = self.transport.get_extra_info('socket')

        return self.__dict__['socket']

    @property
    def tasks(self):
        return self.__dict__['tasks']


class RequestContext(Context):
    def __init__(self):
        self.__dict__ = {
            'options': {}
        }

    @property
    def options(self):
        return self.__dict__['options']
