# Copyright (c) 2023 nggit


class ServerContext:
    def __init__(self):
        self.__dict__ = {
            'options': {},
            'tasks': []
        }

    def __repr__(self):
        return self.__dict__.__repr__()

    @property
    def options(self):
        return self.__dict__['options']

    @property
    def tasks(self):
        return self.__dict__['tasks']

    def set(self, name, value):
        self.__dict__[name] = value

    def get(self, name, default=None):
        return self.__dict__.get(name, default)

    def __setitem__(self, *args):
        self.__setattr__(*args)

    def __getitem__(self, name):
        return self.__dict__[name]
