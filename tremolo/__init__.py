__version__ = '0.2.4'

from .tremolo import Tremolo, Tremolo as Application  # noqa: E402,F401
from . import exceptions  # noqa: E402,F401


def run(app, **options):
    if 'host' not in options:
        options['host'] = '127.0.0.1'

    if 'port' not in options:
        options['port'] = 8000

    Tremolo().run(app=app, **options)
