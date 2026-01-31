import os

from importlib import import_module


def add_package(path, app, base=()):
    if not os.path.isfile(os.path.join(path, '__init__.py')):
        return

    base = (*base, os.path.basename(path))
    basepkg = '.'.join(base)
    basepath = '/' + '/'.join(base)

    app.add_route(import_module(basepkg), basepath)

    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name.startswith(('.', '_')):
                continue

            if entry.is_dir():
                add_module(entry.path, app, base)
                continue

            name, ext = os.path.splitext(entry.name)

            if ext == '.py' and entry.is_file():
                app.add_route(import_module(f'{basepkg}.{name}'),
                              f'{basepath}/{name}')
