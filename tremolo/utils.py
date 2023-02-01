# Copyright (c) 2023 nggit

__all__ = ('html_escape',)

from html import escape  # noqa: E402


def html_escape(data):
    if isinstance(data, str):
        return escape(data)

    return (data.replace(b'&', b'&amp;')
            .replace(b'<', b'&lt;')
            .replace(b'>', b'&gt;')
            .replace(b'"', b'&quot;'))
