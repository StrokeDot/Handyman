"""Interactive glTF viewport: Three.js inside Qt WebEngine, fed by the Blender-authored .glb.

The geometry is never rebuilt here — the viewport loads the exported glTF, so the book it
shows is the same asset Blender renders. The assets are served over localhost because
Chromium refuses to fetch `file://` URLs. The OpenGL viewport stays as the fallback.
"""
import json

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineSettings
    HAVE_WEBENGINE = True
except Exception:                       # WebEngine is an optional install
    QWebEngineView = None
    HAVE_WEBENGINE = False

from viewer_server import ViewerServer


class GltfView(QWidget):
    """A viewport that plays the exported book .glb, with a graceful fallback message."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = None
        self.server = ViewerServer()
        self._loaded = False
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

    # ---------------------------------------------------------------- control
    def _js(self, code):
        if self.view is not None:
            self.view.page().runJavaScript(code)

    def load_book(self, glb_path):
        """Serve the exported .glb and open the viewer on it."""
        if self.view is None:
            return
        url = self.server.publish(glb_path)
        if not self._loaded:
            self.view.load(QUrl(url))
            self.view.loadFinished.connect(
                lambda ok: self._js("loadBook('book.glb')") if ok else None)
            self._loaded = True
        else:
            self._js("loadBook('book.glb')")

    def set_time(self, seconds):
        self._js(f'setTime({float(seconds):.4f})')

    def play(self):
        self._js('window.__playing = true')

    def pause(self):
        self._js('window.__playing = false')

    def set_transform(self, pos, rot, scale):
        self._js(f'setTransform({json.dumps(list(pos))},{json.dumps(list(rot))},{json.dumps(list(scale))})')

    def reset_view(self):
        self._js('resetView()')

    def closeEvent(self, event):
        self.server.stop()
        super().closeEvent(event)
