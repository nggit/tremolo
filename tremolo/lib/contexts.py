# Copyright (c) 2023 nggit


class Context:
    def __init__(self):
        self.__dict__ = {}

    def __repr__(self):
        return self.__dict__.__repr__()

    def get(self, *args):
        return self.__dict__.get(*args)

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
            'queues': {}
        }

    @property
    def options(self):
        return self.__dict__['options']

    @property
    def queues(self):
        return self.__dict__['queues']


class ConnectionContext(Context):
    def __init__(self):
        self.__dict__ = {
            'options': {},
            'tasks': set()
        }

    @property
    def options(self):
        return self.__dict__['options']

    @property
    def tasks(self):
        return self.__dict__['tasks']
