# Copyright (c) 2023 nggit

import traceback

from .exceptions import BadRequest
from .utils import html_escape


async def index(**_):
    return b'Service Unavailable'


async def error_400(**_):
    raise BadRequest


async def error_404(request=None, **_):
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
        b'</body></html>' % request.protocol.options['server_info']['name']
    )


async def error_500(request=None, exc=None, **_):
    if request.protocol.options['debug']:
        return '<ul><li>%s</li></ul>' % '</li><li>'.join(
            traceback.TracebackException.from_exception(exc).format()
        )

    return str(exc)
