"""Interactive glTF viewport: Three.js inside Qt WebEngine, fed by the Blender-authored .glb.

The geometry is *never* rebuilt here — the viewport loads the exported glTF, so the book it
shows is the same asset Blender renders. The OpenGL viewport in live_view.py stays as a
fallback while this pipeline is being proven.
"""
import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineSettings
    HAVE_WEBENGINE = True
except Exception:                       # WebEngine is an optional install
    QWebEngineView = None
    HAVE_WEBENGINE = False


class GltfView(QWidget):
    """A viewport that plays the exported book .glb, with a graceful fallback message."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = None
        self.book_loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if not HAVE_WEBENGINE:
            lay.addWidget(QLabel('Qt WebEngine is not available — the OpenGL viewport stays in use.'))
            return
        self.view = QWebEngineView(self)
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        lay.addWidget(self.view)
        page = Path(__file__).parent / 'resources' / 'viewer' / 'viewer.html'
        self.view.load(QUrl.fromLocalFile(str(page)))

    # ---------------------------------------------------------------- control
    def _js(self, code):
        if self.view is not None:
            self.view.page().runJavaScript(code)

    def load_book(self, glb_path):
        """Point the viewer at an exported .glb (absolute path)."""
        url = QUrl.fromLocalFile(str(glb_path)).toString()
        self._js(f'loadBook({json.dumps(url)})')
        self.book_loaded = True

    def set_time(self, seconds):
        """Scrub: pin every animation to one moment."""
        self._js(f'setTime({float(seconds):.4f})')

    def play(self):
        self._js('window.__playing = true')

    def pause(self):
        self._js('window.__playing = false')

    def set_transform(self, pos, rot, scale):
        self._js(f'setTransform({json.dumps(list(pos))},{json.dumps(list(rot))},{json.dumps(list(scale))})')

    def reset_view(self):
        self._js('resetView()')
