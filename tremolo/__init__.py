from .tremolo import Tremolo
from . import exceptions  # noqa: F401


def run(app, **options):
    if 'host' not in options:
        options['host'] = '127.0.0.1'

    if 'port' not in options:
        options['port'] = 8000

    Tremolo().run(app=app, **options)
