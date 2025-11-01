# https://github.com/nggit/tremolo/discussions/306#discussioncomment-13772290

import os
import stat

from urllib.parse import unquote_to_bytes

from tremolo.exceptions import Forbidden


def file_exists(path, follow_symlinks=True):
    try:
        st = os.stat(path, follow_symlinks=follow_symlinks)

        return stat.S_ISREG(st.st_mode)
    except (OSError, FileNotFoundError):
        return False


class StaticMiddleware:
    def __init__(self, app, **options):
        self.app = app
        self.document_root = os.path.abspath(
            options.get('document_root', os.getcwd())
        )
        self.follow_symlinks = options.get('follow_symlinks', False)
        self.mime_types = {
            # core documents
            '.html': 'text/html; charset=utf-8',
            '.htm': 'text/html; charset=utf-8',
            '.xhtml': 'application/xhtml+xml',

            # styles & scripts
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.mjs': 'application/javascript',
            '.json': 'application/json',

            # images
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',
            '.avif': 'image/avif',

            # fonts
            '.woff2': 'font/woff2',
            '.woff': 'font/woff',
            '.ttf': 'font/ttf',
            '.otf': 'font/otf',

            # audio/video
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',

            # text/plain
            '.txt': 'text/plain',
            '.xml': 'application/xml',

            # JSON-LD (SEO)
            '.jsonld': 'application/ld+json',

            # manifest
            '.webmanifest': 'application/manifest+json',
        }
        self.app.add_middleware(
            self._static_middleware, 'request', priority=9999
        )

    async def _static_middleware(self, request, response, **server):
        path = unquote_to_bytes(request.path).decode('latin-1')
        filepath = os.path.abspath(
            os.path.join(self.document_root,
                         os.path.normpath(path.lstrip('/')))
        )

        if not filepath.startswith(self.document_root):
            raise Forbidden('Path traversal is not allowed')

        if '/.' in path and not path.startswith('/.well-known/'):
            raise Forbidden('Access to dotfiles is prohibited')

        dirname, basename = os.path.split(filepath)
        ext = os.path.splitext(basename)[-1]

        if ext != '' and file_exists(filepath, self.follow_symlinks):
            if ext not in self.mime_types:
                raise Forbidden(f'Disallowed file extension: {ext}')

            await response.sendfile(filepath,
                                    content_type=self.mime_types[ext])
            return True
