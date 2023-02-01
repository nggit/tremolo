# Copyright (c) 2023 nggit


class ServerContext:
    def __init__(self):
        self.__dict__ = {
            'options': {},
            'tasks': [],
            'data': {}
        }

    def __repr__(self):
        return self.__dict__.__repr__()

    @property
    def options(self):
        return self.__dict__['options']

    @property
    def tasks(self):
        return self.__dict__['tasks']

    @property
    def data(self):
        return self.__dict__['data']

    def set(self, name, value):
        self.__dict__[name] = value
