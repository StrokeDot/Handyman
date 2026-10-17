"""Live 3D preview of the book inside the app (OpenGL). No Blender, no waiting.

Draws the same book as the final render (shared book_model / page_curl / camera_fit), with
the page images on the pages, lighting, cover opening and page turns. Play, pause, scrub and
change speed; drag with the mouse to move the camera. Blender is only needed for the final video.
"""
import math

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

import book_model as bm
import camera_fit as cf
from page_curl import Timeline, grid_faces, grid_uvs, layout_pages, sheet_vertices

try:
    from OpenGL import GL as gl
    GL_IMPORT_ERROR = None
except Exception as exc:  # PyOpenGL missing or no OpenGL driver
    gl = None
    GL_IMPORT_ERROR = str(exc)

NX, NY = 40, 24
TEX_W = 512


def _hex_rgb(value):
    value = (value or '#808080').lstrip('#')
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _flip_v(img):
    return img.flipped(Qt.Orientation.Vertical) if hasattr(img, 'flipped') else img.mirrored(False, True)


def _smooth_noise(rng, cx, cy, h, w):
    """Random grid of cy × cx values, bilinearly stretched to h × w (no blocky squares)."""
    g = rng.random((cy + 1, cx + 1)).astype(np.float32)
    ys = np.linspace(0, cy, h, dtype=np.float32)
    xs = np.linspace(0, cx, w, dtype=np.float32)
    y0 = np.minimum(ys.astype(int), cy - 1)
    x0 = np.minimum(xs.astype(int), cx - 1)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    a, b = g[y0][:, x0], g[y0][:, x0 + 1]
    c, d = g[y0 + 1][:, x0], g[y0 + 1][:, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def paper_image(book, aspect, seed):
    """Aged paper with darker burnt edges, like the final render's paper (approximation)."""
    h = int(TEX_W * aspect)
    rng = np.random.default_rng(seed)
    fresh = np.array(_hex_rgb(book.get('paper_color')))
    age = float(book.get('paper_age', 0.5))
    burn = float(book.get('burn', 0.5))
    old = fresh * np.array([0.78, 0.68, 0.52])
    base = fresh + (old - fresh) * age
    # Soft blotches: a few octaves of smoothly upsampled random noise.
    blot = np.zeros((h, TEX_W), dtype=np.float32)
    for cells, weight in ((5, 1.0), (11, 0.5), (23, 0.25)):
        blot += weight * _smooth_noise(rng, cells, max(2, int(cells * aspect)), h, TEX_W)
    shade = 1.0 - 0.18 * age * (blot - blot.mean()) / (blot.std() + 1e-6) * 0.5
    v, u = np.mgrid[0:h, 0:TEX_W]
    edge = np.minimum(np.minimum(u, TEX_W - 1 - u) / TEX_W, np.minimum(v, h - 1 - v) / h)
    edge = edge + 0.02 * (rng.random((h, TEX_W)) - 0.5)
    vign = np.clip(1.0 - edge / (0.03 + 0.07 * burn), 0, 1) ** 1.5 * 0.9 * burn
    rgb = base[None, None, :] * shade[..., None]
    rgb = rgb * (1 - vign[..., None]) + rgb * np.array([0.30, 0.16, 0.07]) * vign[..., None]
    arr = np.dstack([np.clip(rgb, 0, 1) * 255, np.full((h, TEX_W), 255)]).astype(np.uint8)
    img = QImage(arr.tobytes(), TEX_W, h, TEX_W * 4, QImage.Format.Format_RGBA8888)
    return img.copy()


def page_image(book, aspect, path, blend, margin=0.08, seed=0):
    img = paper_image(book, aspect, seed)
    if path:
        src = QImage(path)
        if not src.isNull():
            w, h = img.width(), img.height()
            mw = margin * w
            k = min((w - 2 * mw) / src.width(), (h - 2 * mw) / src.height())
            dw, dh = src.width() * k, src.height() * k
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if blend == 'ink':
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            p.setOpacity(0.92)
            p.drawImage(QRectF((w - dw) / 2, (h - dh) / 2, dw, dh), src)
            p.end()
    return img


def text_image(text, colour):
    font = QFont('Georgia', 64)
    probe = QImage(8, 8, QImage.Format.Format_RGBA8888)
    p = QPainter(probe)
    p.setFont(font)
    rect = p.fontMetrics().boundingRect(text)
    p.end()
    img = QImage(rect.width() + 24, rect.height() + 12, QImage.Format.Format_RGBA8888)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    p.setPen(QColor(*[int(c * 255) for c in colour]))
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


def grid_normals(v):
    g = v.reshape(NY, NX, 3)
    du = np.gradient(g, axis=1)
    dv = np.gradient(g, axis=0)
    n = np.cross(du, dv)
    n /= np.linalg.norm(n, axis=2, keepdims=True) + 1e-12
    return n.reshape(-1, 3)


class LiveView(QOpenGLWidget):
    orbit = Signal(float, float)
    pan = Signal(float, float)
    zoomed = Signal(int)
    reset = Signal()
    frameChanged = Signal(int, int)       # frame, total
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        fmt.setDepthBufferSize(24)
        self.setFormat(fmt)
        self.setMinimumHeight(220)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('Drag to look around the book · right-drag to move it · wheel to zoom · double-click to reset')
        self.cam = dict(cf.PRESETS['Eye level (reading at a desk)'], zoom=1.0, move='none')
        self.aspect = 16 / 9
        self.book = None
        self.images = []
        self.values = None
        self.layout = None
        self.timeline = Timeline(1, 30)
        self.frame = 0.0
        self.speed = 1.0
        self.playing = False
        self.loop = True
        self.broken = None
        self._textures = {}
        self._dirty_textures = True
        self._sheet_cache = {}
        self._last = None
        self._button = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        self._clock = None
        self.uvs = grid_uvs(NX, NY).astype(np.float32)
        self.uvs_back = self.uvs.copy()
        self.uvs_back[:, 0] = 1.0 - self.uvs_back[:, 0]
        self.tris = np.array([(a, b, c) for q in grid_faces(NX, NY) for a, b, c in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))],
                             dtype=np.uint32).ravel()

    # ------------------------------------------------------------ public API
    def set_view(self, cam, page_aspect=None, aspect=None):
        self.cam = dict(cam)
        if aspect:
            self.aspect = aspect
        self.update()

    def set_content(self, book, images, values):
        """book: template dict; images: page paths (None = blank); values: the app's settings."""
        key_tex = (book.get('folder'), tuple(sorted((k, str(v)) for k, v in book.items())), tuple(images),
                   values.get('blend'))
        if key_tex != getattr(self, '_key_tex', None):
            self._key_tex = key_tex
            self._dirty_textures = True
        self.book, self.images, self.values = book, list(images), dict(values)
        turns = layout_pages(len(images))[0]
        self.layout = bm.Layout(book.get('page_aspect', 1.4), turns, values.get('open_at', 0.04))
        v = values
        self.timeline = Timeline(turns, v['fps'], v['start_hold'], v['turn_seconds'], v['pause'], v['end_hold'],
                                 v['open_seconds'] if v.get('start_closed') else 0.0)
        self.frame = min(self.frame, self.timeline.frames - 1)
        self._sheet_cache.clear()
        self.cam = dict(v.get('cam', self.cam))
        self.aspect = v['width'] / v['height']
        self.frameChanged.emit(int(self.frame), self.timeline.frames)
        self.update()

    def play(self, on=True):
        if on and self.frame >= self.timeline.frames - 1:
            self.frame = 0.0
        self.playing = on
        self._clock = None

    def seek(self, frame):
        self.frame = float(max(0, min(frame, self.timeline.frames - 1)))
        self.frameChanged.emit(int(self.frame), self.timeline.frames)
        self.update()

    # ------------------------------------------------------------- playback
    def _tick(self):
        if not self.playing:
            return
        import time
        now = time.perf_counter()
        if self._clock is None:
            self._clock = now
            return
        dt, self._clock = now - self._clock, now
        self.frame += dt * self.timeline.fps * self.speed
        if self.frame >= self.timeline.frames - 1:
            if self.loop:
                self.frame = 0.0
            else:
                self.frame = self.timeline.frames - 1
                self.playing = False
        self.frameChanged.emit(int(self.frame), self.timeline.frames)
        self.update()

    # ----------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        self._last, self._button = e.position(), e.button()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._last is None:
            return
        d = e.position() - self._last
        self._last = e.position()
        (self.orbit if self._button == Qt.MouseButton.LeftButton else self.pan).emit(d.x(), d.y())

    def mouseReleaseEvent(self, _):
        self._last = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, _):
        self.reset.emit()

    def wheelEvent(self, e):
        steps = round(e.angleDelta().y() / 120)
        if steps:
            self.zoomed.emit(steps)

    # -------------------------------------------------------------- textures
    def _upload(self, key, img, clamp=True):
        img = _flip_v(img.convertToFormat(QImage.Format.Format_RGBA8888))
        tid = self._textures.get(key) or gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tid)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        wrap = gl.GL_CLAMP_TO_EDGE if clamp else gl.GL_REPEAT
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, wrap)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, wrap)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_GENERATE_MIPMAP, gl.GL_TRUE)
        ptr = img.constBits()
        data = bytes(ptr) if not isinstance(ptr, (bytes, bytearray)) else ptr
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, img.width(), img.height(), 0, gl.GL_RGBA,
                        gl.GL_UNSIGNED_BYTE, data[:img.width() * img.height() * 4])
        self._textures[key] = tid
        return tid

    def _build_textures(self):
        book, images = self.book, self.images
        aspect = float(book.get('page_aspect', 1.4))
        blend = self.values.get('blend', 'ink')
        get = lambda i: images[i] if i is not None and i < len(images) else None  # noqa: E731
        turns, left_i, sheets, right_i = layout_pages(len(images))
        self._tex_pages = {'blank': self._upload('blank', page_image(book, aspect, None, blend, seed=1)),
                           'left': self._upload('left', page_image(book, aspect, get(left_i), blend, seed=2)),
                           'right': self._upload('right', page_image(book, aspect, get(right_i), blend, seed=3))}
        for k, (f, b) in enumerate(sheets):
            self._tex_pages[('f', k)] = self._upload(('f', k), page_image(book, aspect, get(f), blend, seed=10 + k))
            self._tex_pages[('b', k)] = self._upload(('b', k), page_image(book, aspect, get(b), blend, seed=50 + k))
        self._emblem = None
        if book.get('emblem') and book.get('folder'):
            from pathlib import Path
            p = Path(book['folder']) / book['emblem']
            img = QImage(str(p))
            if not img.isNull():
                self._emblem = (self._upload('emblem', img), img.width() / img.height())
        self._title = None
        if (book.get('title') or '').strip():
            leather = np.array(_hex_rgb(book.get('leather_color')))
            colour = (0.85, 0.62, 0.25) if book.get('title_style') == 'gold' else tuple(leather * 0.35)
            img = text_image(book['title'].strip(), colour)
            self._title = (self._upload('title', img), img.width() / img.height())
        self._dirty_textures = False

    # -------------------------------------------------------------------- GL
    def initializeGL(self):
        if gl is None:
            self.broken = GL_IMPORT_ERROR or 'OpenGL is not available'
            self.failed.emit(self.broken)
            return
        try:
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glEnable(gl.GL_NORMALIZE)
            gl.glShadeModel(gl.GL_SMOOTH)
            gl.glEnable(gl.GL_LIGHT0)
            gl.glEnable(gl.GL_LIGHT1)
            gl.glLightModeli(gl.GL_LIGHT_MODEL_TWO_SIDE, gl.GL_TRUE)
            gl.glEnable(gl.GL_COLOR_MATERIAL)
            gl.glColorMaterial(gl.GL_FRONT_AND_BACK, gl.GL_AMBIENT_AND_DIFFUSE)
            gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT, (0.34, 0.32, 0.30, 1.0))
            gl.glLightfv(gl.GL_LIGHT0, gl.GL_DIFFUSE, (1.0, 0.9, 0.78, 1.0))
            gl.glLightfv(gl.GL_LIGHT0, gl.GL_SPECULAR, (0.25, 0.22, 0.2, 1.0))
            gl.glLightfv(gl.GL_LIGHT1, gl.GL_DIFFUSE, (0.22, 0.24, 0.28, 1.0))
            gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_SPECULAR, (0.12, 0.12, 0.12, 1.0))
            gl.glMaterialf(gl.GL_FRONT_AND_BACK, gl.GL_SHININESS, 24.0)
            gl.glHint(gl.GL_PERSPECTIVE_CORRECTION_HINT, gl.GL_NICEST)
        except Exception as exc:
            self.broken = str(exc)
            self.failed.emit(self.broken)

    def paintGL(self):
        if self.broken or gl is None:
            return
        try:
            self._paint()
        except Exception as exc:
            self.broken = f'{type(exc).__name__}: {exc}'
            self.failed.emit(self.broken)

    def _frame_rect(self):
        dpr = self.devicePixelRatioF()
        W, H = int(self.width() * dpr), int(self.height() * dpr)
        h = min(H, int(W / self.aspect))
        w = int(h * self.aspect)
        return (W - w) // 2, (H - h) // 2, w, h, W, H

    def _checker(self, W, H, x0, y0, w, h):
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glViewport(0, 0, W, H)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, W, 0, H, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        s = max(8, int(16 * self.devicePixelRatioF()))
        gl.glBegin(gl.GL_QUADS)
        for yy in range(y0, y0 + h, s):
            for xx in range(x0, x0 + w, s):
                c = 0.29 if ((xx - x0) // s + (yy - y0) // s) % 2 else 0.22
                gl.glColor3f(c, c, c + 0.02)
                x1, y1 = min(xx + s, x0 + w), min(yy + s, y0 + h)
                gl.glVertex2f(xx, yy)
                gl.glVertex2f(x1, yy)
                gl.glVertex2f(x1, y1)
                gl.glVertex2f(xx, y1)
        gl.glEnd()
        gl.glEnable(gl.GL_DEPTH_TEST)

    def _paint(self):
        x0, y0, w, h, W, H = self._frame_rect()
        gl.glClearColor(0.15, 0.15, 0.17, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        self._checker(W, H, x0, y0, w, h)
        if self.book is None or self.layout is None:
            return
        if self._dirty_textures:
            self._build_textures()
        L = self.layout
        tl = self.timeline
        f = self.frame
        frac = f / max(1, tl.frames - 1)

        # Camera, exactly as the final render frames it.
        top = L.camera_top()
        pts = cf.book_points(L.page_w, L.page_h, bm.COVER_MARGIN, top)
        cam, r, u, fw, lens = cf.shot(self.cam, frac, (0.0, 0.0, top), L.book_w, L.cover_h, pts, self.aspect)
        gl.glViewport(x0, y0, w, h)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        th = cf.SENSOR / 2 / lens
        near, far = 0.05, 200.0
        gl.glFrustum(-th * near, th * near, -th / self.aspect * near, th / self.aspect * near, near, far)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        view = np.eye(4)
        view[0, :3], view[1, :3], view[2, :3] = r, u, -np.asarray(fw)
        view[:3, 3] = -view[:3, :3] @ cam
        gl.glLoadMatrixd(view.T.ravel())
        # Lights in world space (the sun of the final render, plus a cool fill from the other side).
        sun = np.array([0.45, -0.55, 0.85])
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_POSITION, (*(sun / np.linalg.norm(sun)), 0.0))
        gl.glLightfv(gl.GL_LIGHT1, gl.GL_POSITION, (-0.6, 0.4, 0.5, 0.0))
        gl.glEnable(gl.GL_LIGHTING)

        angle, slide = L.opening(tl.opening(f), self.values.get('start_closed', True))
        gl.glPushMatrix()
        gl.glTranslatef(slide, 0, 0)
        leather = _hex_rgb(self.book.get('leather_color'))
        edge = np.array(_hex_rgb(self.book.get('paper_color'))) * 0.85
        m, hy = bm.COVER_MARGIN, L.cover_h / 2

        # Right half.
        self._box(0, L.page_w + m, -hy, hy, 0, bm.COVER_T, leather)
        self._prism(*bm.block_prism(L, 1), edge)
        self._sheet(0.0, L.base_right, L.base_right, self._tex_pages['right'], self._tex_pages['blank'])
        turns, *_ = layout_pages(len(self.images))
        for k in range(turns):
            zr, zl = L.sheet_levels(k)
            self._sheet(tl.progress(f, k), zr, zl, self._tex_pages[('f', k)], self._tex_pages[('b', k)], k)
        self._spine(angle / math.pi, leather)

        # Left half, on the hinge.
        gl.glPushMatrix()
        gl.glTranslatef(0, 0, L.hinge)
        gl.glRotatef(math.degrees(angle), 0, 1, 0)
        gl.glTranslatef(0, 0, -L.hinge)
        self._box(-L.page_w - m, 0, -hy, hy, 0, bm.COVER_T, leather)
        self._prism(*bm.block_prism(L, -1), edge)
        self._sheet(1.0, L.base_left, L.base_left, self._tex_pages['blank'], self._tex_pages['left'])
        self._cover_art(L)
        gl.glPopMatrix()
        gl.glPopMatrix()

    # ------------------------------------------------------------- drawing
    def _box(self, x0, x1, y0, y1, z0, z1, colour):
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glColor3f(*colour)
        gl.glBegin(gl.GL_QUADS)
        for n, quad in (((0, 0, 1), ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))),
                        ((0, 0, -1), ((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0))),
                        ((0, -1, 0), ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))),
                        ((0, 1, 0), ((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0))),
                        ((1, 0, 0), ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))),
                        ((-1, 0, 0), ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)))):
            gl.glNormal3f(*n)
            for p in quad:
                gl.glVertex3f(*p)
        gl.glEnd()

    def _prism(self, verts, faces, colour):
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glColor3f(*colour)
        for face in faces:
            p = verts[list(face)]
            n = np.cross(p[1] - p[0], p[-1] - p[0])
            if np.linalg.norm(n) < 1e-12 and len(p) > 3:
                n = np.cross(p[2] - p[1], p[0] - p[1])
            gl.glBegin(gl.GL_POLYGON)
            gl.glNormal3f(*(n / (np.linalg.norm(n) + 1e-12)))
            for q in p:
                gl.glVertex3f(*q)
            gl.glEnd()

    def _sheet(self, t, zr, zl, tex_front, tex_back, key=None):
        L = self.layout
        ck = (key, round(t, 4), zr, zl)
        if ck not in self._sheet_cache:
            v = sheet_vertices(t, L.page_w, L.page_h, NX, NY, zr, zl,
                               curl=self.values.get('curl', 0.9), gutter=L.gutter).astype(np.float32)
            self._sheet_cache[ck] = (v, grid_normals(v).astype(np.float32))
            if len(self._sheet_cache) > 400:
                self._sheet_cache.clear()
        v, n = self._sheet_cache[ck]
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glColor3f(1, 1, 1)
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
        gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
        gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glVertexPointer(3, gl.GL_FLOAT, 0, v)
        gl.glNormalPointer(gl.GL_FLOAT, 0, n)
        gl.glEnable(gl.GL_CULL_FACE)
        for tex, uv, cull in ((tex_front, self.uvs, gl.GL_BACK), (tex_back, self.uvs_back, gl.GL_FRONT)):
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glTexCoordPointer(2, gl.GL_FLOAT, 0, uv)
            gl.glCullFace(cull)
            gl.glDrawElements(gl.GL_TRIANGLES, len(self.tris), gl.GL_UNSIGNED_INT, self.tris)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY)
        gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glDisable(gl.GL_TEXTURE_2D)

    def _spine(self, closed, colour):
        if not hasattr(self, '_spine_data') or self._spine_data[0] is not self.layout:
            o, c, faces = bm.spine_shapes(self.layout, int(self.book.get('spine_bands', 4)))
            self._spine_data = (self.layout, o, c, faces)
        _, o, c, faces = self._spine_data
        v = o + (c - o) * closed
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glColor3f(*(np.array(colour) * 0.9))
        gl.glBegin(gl.GL_QUADS)
        for face in faces:
            p = v[list(face)]
            nrm = np.cross(p[1] - p[0], p[3] - p[0])
            gl.glNormal3f(*(-nrm / (np.linalg.norm(nrm) + 1e-12)))
            for q in p:
                gl.glVertex3f(*q)
        gl.glEnd()

    def _cover_art(self, L):
        """Emblem, title and stitching on the front cover (placed as on the closed book)."""
        b = self.book
        cw, ch = L.cover_w, L.cover_h
        cx, z_top = cw / 2, 2 * L.hinge

        def quad(tex, cy, w, h, lift):
            corners = [(cx - w / 2, cy - h / 2, 0, 0), (cx + w / 2, cy - h / 2, 1, 0),
                       (cx + w / 2, cy + h / 2, 1, 1), (cx - w / 2, cy + h / 2, 0, 1)]
            gl.glEnable(gl.GL_TEXTURE_2D)
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glEnable(gl.GL_ALPHA_TEST)
            gl.glAlphaFunc(gl.GL_GREATER, 0.05)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glDisable(gl.GL_LIGHTING)          # printed art: show its own colours
            gl.glColor3f(0.92, 0.9, 0.88)
            gl.glBegin(gl.GL_QUADS)
            for x, y, s, t in reversed(corners):
                gl.glTexCoord2f(s, t)
                gl.glVertex3f(*bm.closed_to_open(L, x, y, z_top + lift))
            gl.glEnd()
            gl.glEnable(gl.GL_LIGHTING)
            gl.glDisable(gl.GL_ALPHA_TEST)
            gl.glDisable(gl.GL_BLEND)
            gl.glDisable(gl.GL_TEXTURE_2D)

        if self._emblem:
            size = float(b.get('emblem_size', 0.4)) * cw
            quad(self._emblem[0], float(b.get('emblem_y', 0.18)) * ch, size, size / self._emblem[1], 0.0015)
        if self._title:
            th = float(b.get('title_size', 0.07)) * ch * 1.3
            quad(self._title[0], float(b.get('title_y', -0.08)) * ch, th * self._title[1], th, 0.0012)
        if b.get('stitching', True):
            colour = _hex_rgb(b.get('thread_color', '#b08a5a'))
            gl.glColor3f(*colour)
            gl.glLineWidth(max(1.0, 1.6 * self.devicePixelRatioF()))
            inset = 0.035
            x0, x1 = cx - cw / 2 + inset, cx + cw / 2 - inset
            y0, y1 = -ch / 2 + inset, ch / 2 - inset
            gl.glNormal3f(0, 0, -1)
            gl.glBegin(gl.GL_LINES)
            step, dash = 0.035, 0.022
            for x in np.arange(x0, x1 - dash, step):
                for y in (y0, y1):
                    gl.glVertex3f(*bm.closed_to_open(L, x, y, z_top + 0.001))
                    gl.glVertex3f(*bm.closed_to_open(L, x + dash, y, z_top + 0.001))
            for y in np.arange(y0, y1 - dash, step):
                for x in (x0, x1):
                    gl.glVertex3f(*bm.closed_to_open(L, x, y, z_top + 0.001))
                    gl.glVertex3f(*bm.closed_to_open(L, x, y + dash, z_top + 0.001))
            gl.glEnd()
