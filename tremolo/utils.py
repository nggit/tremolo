# Copyright (c) 2023 nggit

__all__ = ('file_signature', 'html_escape', 'log_date', 'server_date')

import os  # noqa: E402
import stat  # noqa: E402

from datetime import datetime  # noqa: E402
from html import escape  # noqa: E402


def file_signature(path):
    st = os.stat(path)

    return (stat.S_IFMT(st.st_mode), st.st_size, st.st_mtime)


def html_escape(data):
    if isinstance(data, str):
        return escape(data)

    return (data.replace(b'&', b'&amp;')
            .replace(b'<', b'&lt;')
            .replace(b'>', b'&gt;')
            .replace(b'"', b'&quot;'))


def log_date():
    return datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')


def server_date():
    return datetime.utcnow().strftime(
        '%a, %d %b %Y %H:%M:%S GMT').encode('latin-1')
