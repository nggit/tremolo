# Copyright (c) 2023 nggit

from .exceptions import BadRequest
from .utils import html_escape


async def index(**_):
    return b'Service Unavailable'


async def error_400(**_):
    raise BadRequest


async def error_404(**server):
    yield (
        b'<!DOCTYPE html><html lang="en"><head><meta name="viewport" '
        b'content="width=device-width, initial-scale=1.0" />'
        b'<title>404 Not Found</title>'
        b'<style>body { max-width: 600px; margin: 0 auto; padding: 1%; '
        b'font-family: sans-serif; line-height: 1.5em; }</style></head>'
        b'<body><h1>Not Found</h1>'
    )
    yield (b'<p>Unable to find handler for %s.</p><hr />' %
           html_escape(server['request'].path))
    yield (
        b'<address title="Powered by Tremolo">%s</address>'
        b'</body></html>' % server['context'].options['server_name']
    )
