"""A tiny localhost HTTP server for the glTF viewer.

Chromium refuses to fetch `file://` URLs, so the viewer assets and the current `.glb` are
copied into a cache folder and served over 127.0.0.1. No Qt here, so it is testable.
"""
import functools
import http.server
import shutil
import threading
from pathlib import Path

import paths

VIEWER_SRC = Path(__file__).parent / 'resources' / 'viewer'


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def guess_type(self, path):
        if str(path).endswith('.glb'):
            return 'model/gltf-binary'
        return super().guess_type(path)


class ViewerServer:
    def __init__(self):
        self.httpd = None
        self.port = None
        self.root = None
        self._thread = None

    def publish(self, glb_path):
        """Copy the viewer + the .glb into a served folder and return the viewer URL."""
        self.root = Path(paths.cache_dir('viewer'))
        for item in VIEWER_SRC.rglob('*'):
            if item.is_file():
                dst = self.root / item.relative_to(VIEWER_SRC)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, dst)
        shutil.copyfile(glb_path, self.root / 'book.glb')
        if self.httpd is None:
            handler = functools.partial(_QuietHandler, directory=str(self.root))
            self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            self.port = self.httpd.server_address[1]
            self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self._thread.start()
        return f'http://127.0.0.1:{self.port}/viewer.html'

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
