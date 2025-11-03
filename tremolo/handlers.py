# SPDX-License-Identifier: MIT
# Copyright (c) 2023 Anggit Arfanto

from traceback import TracebackException

from .utils import html_escape


async def index(status=(503, b'Service Unavailable')):
    return b'Service Unavailable'


async def error_400(exc, **_):
    return str(exc)


async def error_404(request, **_):
    return (
        b'<!DOCTYPE html><html lang="en"><head><meta name="viewport" '
        b'content="width=device-width, initial-scale=1.0" />'
        b'<title>404 Not Found</title>'
        b'<style>body { max-width: 600px; margin: 0 auto; padding: 1%%; '
        b'font-family: sans-serif; line-height: 1.5em; }</style></head>'
        b'<body><h1>Not Found</h1><p>Unable to find handler for %s.</p><hr />'
        b'<address title="Powered by Tremolo">%s</address></body></html>' %
        (html_escape(request.path), request.server.globals.info['server_name'])
    )


async def error_405(exc, **_):
    return str(exc)


async def error_500(request, exc, **_):
    if request.protocol is None:
        return

    if request.protocol.options['debug']:
        te = TracebackException.from_exception(exc)
        return '<ul><li>%s</li></ul>' % '</li><li>'.join(
            html_escape(line) for line in te.format()
        )

    return str(exc)
