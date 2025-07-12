# Copyright (c) 2023 nggit

from traceback import TracebackException

from .exceptions import BadRequest, MethodNotAllowed
from .utils import html_escape


async def index(**_):
    return b'Service Unavailable'


async def error_400(**_):
    raise BadRequest


async def error_404(request, globals, **_):
    yield (
        b'<!DOCTYPE html><html lang="en"><head><meta name="viewport" '
        b'content="width=device-width, initial-scale=1.0" />'
        b'<title>404 Not Found</title>'
        b'<style>body { max-width: 600px; margin: 0 auto; padding: 1%; '
        b'font-family: sans-serif; line-height: 1.5em; }</style></head>'
        b'<body><h1>Not Found</h1>'
    )
    yield (b'<p>Unable to find handler for %s.</p><hr />' %
           html_escape(request.path))
    yield (
        b'<address title="Powered by Tremolo">%s</address>'
        b'</body></html>' % globals.info['server_name']
    )


async def error_405(**_):
    raise MethodNotAllowed


async def error_500(request, exc=None, **_):
    if exc is None or request.protocol is None:
        return

    if request.protocol.options['debug']:
        te = TracebackException.from_exception(exc)
        return '<ul><li>%s</li></ul>' % '</li><li>'.join(
            html_escape(line) for line in te.format()
        )

    return str(exc)
