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
import paths
import scene
from drag import DragState
from page_curl import grid_faces, grid_uvs, layout_pages, sheet_vertices

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


def _resolve_texture(book, key):
    """Find a bundled/relative texture, matching templates.for_scene."""
    name = book.get(key)
    if not name:
        return None
    from pathlib import Path
    cands = []
    if book.get('folder'):
        cands.append(Path(book['folder']) / name)
    cands.append(paths.resource_dir() / name)
    for p in cands:
        if p.exists():
            return str(p)
    return None


def page_image(book, aspect, path, blend, margin=0.08, seed=0, fit=None):
    paper_path = _resolve_texture(book, 'paper_image')
    base = QImage(paper_path) if paper_path else QImage()
    if paper_path and not base.isNull():
        img = base.scaled(TEX_W, int(TEX_W * aspect), Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    else:
        img = paper_image(book, aspect, seed)
    if path:
        src = QImage(path)
        if not src.isNull():
            w, h = img.width(), img.height()
            f = fit or {}
            mode = f.get('mode', 'fit')
            scale = max(0.05, float(f.get('scale', 1.0)))
            ox = float(f.get('x', 0.0))
            oy = float(f.get('y', 0.0))
            mw = margin * w if mode == 'fit' else 0.0
            avw, avh = w - 2 * mw, h - 2 * mw
            if mode == 'stretch':
                dw, dh = avw, avh
            elif mode == 'fill':
                k = max(avw / src.width(), avh / src.height())
                dw, dh = src.width() * k, src.height() * k
            else:                                # 'fit'
                k = min(avw / src.width(), avh / src.height())
                dw, dh = src.width() * k, src.height() * k
            dw *= scale
            dh *= scale
            cx, cy = w / 2 + ox * w, h / 2 + oy * h
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if blend == 'ink':
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            p.setOpacity(0.92)
            p.drawImage(QRectF(cx - dw / 2, cy - dh / 2, dw, dh), src)
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
    pageTurned = Signal(int, int, float)  # start frame, duration, smoothness (record mode)

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
        self.scene = scene.Scene(1)
        self.timeline = self.scene.timeline
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
        self.page_drag = DragState()
        self.drag_pages = False
        self.drag_sheet = None
        self.drag_progress = 0.0
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
        v = values
        self.scene = scene.Scene(turns, book.get('page_aspect', 1.4), values.get('open_at', 0.04),
                                 v['fps'], v['start_hold'], v['turn_seconds'], v['pause'], v['end_hold'],
                                 v['open_seconds'] if v.get('start_closed') else 0.0,
                                 v.get('start_closed', True), page_count=values.get('page_count'),
                                 smoothness=values.get('smoothness', 1.0),
                                 recorded_clips=values.get('recorded_clips'),
                                 clip_list=values.get('clip_list'))
        self.layout = self.scene.layout
        self.timeline = self.scene.timeline
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
    def _next_sheet(self):
        """The sheet the user would turn next: the first one still on the right."""
        if self.scene is None:
            return None
        for k, p in enumerate(self.scene.evaluate(self.frame)['sheet_progress']):
            if p < 1.0:
                return k
        return None

    def mousePressEvent(self, e):
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if (self.drag_pages or shift) and e.button() == Qt.MouseButton.LeftButton:
            sheet = self._next_sheet()
            if sheet is not None:
                self.drag_sheet = sheet
                self.drag_progress = 0.0
                self.page_drag.begin(e.position().x(), e.position().y())
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        self._last, self._button = e.position(), e.button()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self.drag_sheet is not None:
            span = max(1.0, self.width() * 0.55)
            self.drag_progress = self.page_drag.move(e.position().x(), e.position().y(), span)
            self.update()
            return
        if self._last is None:
            return
        d = e.position() - self._last
        self._last = e.position()
        (self.orbit if self._button == Qt.MouseButton.LeftButton else self.pan).emit(d.x(), d.y())

    def mouseReleaseEvent(self, _):
        if self.drag_sheet is not None:
            done = self.page_drag.finish()
            k = self.drag_sheet
            self.drag_sheet = None
            self.drag_progress = 0.0
            if done >= 1.0:
                tl = self.timeline
                start = int(self.frame)
                self.pageTurned.emit(start, int(tl.turn), float(self.values.get('smoothness', 1.0)))
                self.seek(min(tl.frames - 1, tl.turn_start(k) + tl.turn))
            self.update()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
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
        fits = self.values.get('page_fits') or []
        fit_of = lambda i: fits[i] if i is not None and i < len(fits) else None  # noqa: E731
        turns, left_i, sheets, right_i = layout_pages(len(images))
        # Blender skips the resting left page when there is no left-hand page yet (the first
        # spread shows the front pastedown). The live view must match, or it draws an extra
        # blank sheet over the pastedown.
        self._has_left_page = left_i is not None
        self._tex_pages = {'blank': self._upload('blank', page_image(book, aspect, None, blend, seed=1)),
                           'left': self._upload('left', page_image(book, aspect, get(left_i), blend, seed=2, fit=fit_of(left_i))),
                           'right': self._upload('right', page_image(book, aspect, get(right_i), blend, seed=3, fit=fit_of(right_i)))}
        n_turns = self.scene.turns if getattr(self, 'scene', None) else len(sheets)
        for k in range(n_turns):
            f, b = sheets[k] if k < len(sheets) else (None, None)
            self._tex_pages[('f', k)] = self._upload(('f', k), page_image(book, aspect, get(f), blend, seed=10 + k, fit=fit_of(f)))
            self._tex_pages[('b', k)] = self._upload(('b', k), page_image(book, aspect, get(b), blend, seed=50 + k, fit=fit_of(b)))
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
        self._tex_leather = None
        lp = _resolve_texture(book, 'leather_image')
        if lp:
            img = QImage(str(lp))
            if not img.isNull():
                self._tex_leather = self._upload('leather', img)
        self._tex_surface = {}
        self._surface_aspect = {}
        for field in ('front_exterior_image', 'front_interior_image', 'back_exterior_image',
                      'back_interior_image', 'spine_exterior_image'):
            p = _resolve_texture(book, field)
            if p:
                img = QImage(str(p))
                if not img.isNull():
                    self._tex_surface[field] = self._upload(field, img)
                    self._surface_aspect[field] = img.height() / max(1, img.width())
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
        f = self.frame
        pose = self.scene.evaluate(f)
        frac = pose['camera_frac']

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

        angle, slide = pose['cover_angle'], pose['cover_slide']
        tf = self.values.get('transform') or {}
        pos = tf.get('pos', (0.0, 0.0, 0.0))
        rot = tf.get('rot', (0.0, 0.0, 0.0))
        scale = tf.get('scale', (1.0, 1.0, 1.0))
        gl.glPushMatrix()
        gl.glTranslatef(float(pos[0]), float(pos[1]), float(pos[2]))
        gl.glRotatef(float(rot[2]), 0, 0, 1)
        gl.glRotatef(float(rot[1]), 0, 1, 0)
        gl.glRotatef(float(rot[0]), 1, 0, 0)
        gl.glScalef(float(scale[0]), float(scale[1]), float(scale[2]))
        gl.glTranslatef(slide, 0, 0)
        leather = _hex_rgb(self.book.get('leather_color'))
        back_leather = _hex_rgb(self.book.get('back_cover_color') or self.book.get('leather_color'))
        endpaper = _hex_rgb(self.book.get('inside_cover_color') or self.book.get('leather_color'))
        edge = np.array(_hex_rgb(self.book.get('paper_color'))) * 0.85
        m, hy = bm.COVER_MARGIN, L.cover_h / 2

        # Right half.
        if not self._tex_box(0, L.page_w + m, -hy, hy, 0, bm.COVER_T, self._tex_surface.get('back_exterior_image') or self._tex_leather, uv=self._surface_uv('back_exterior_image')):
            self._box(0, L.page_w + m, -hy, hy, 0, bm.COVER_T, back_leather)
        self._endpaper(0, L.page_w + m, -hy, hy, endpaper, self._tex_surface.get('back_interior_image') or self._tex_leather, uv=self._surface_uv('back_interior_image'))
        for j in range(L.right_rest_count):
            self._prism(*bm.sheet_slice(L, 1, j, L.right_rest_count), edge)
        self._sheet(0.0, L.base_right + 0.0015, L.base_right + 0.0015, self._tex_pages['right'], self._tex_pages['blank'])
        for k in range(L.turns):
            zr, zl = L.turn_levels(k)
            t = self.drag_progress if k == self.drag_sheet else pose['sheet_progress'][k]
            self._sheet(t, zr, zl, self._tex_pages[('f', k)], self._tex_pages[('b', k)], k,
                        smoothness=pose['smoothness'])
        self._spine(angle / math.pi, leather)
        # Spine lining: covers the gutter side of the page block (the bright paper edge) and
        # any hole beneath the opening cover. Drawn on both faces so it reads from either side.
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glColor3f(*(np.array(leather) * 0.6))
        z_top = float(L.base_right)
        for nx in (1.0, -1.0):
            gl.glNormal3f(nx, 0, 0)
            gl.glBegin(gl.GL_QUADS)
            for p in ((-0.0012 * nx, -hy, 0.0), (-0.0012 * nx, -hy, z_top),
                      (-0.0012 * nx, hy, z_top), (-0.0012 * nx, hy, 0.0)):
                gl.glVertex3f(*p)
            gl.glEnd()

        self._hinge(angle, leather)
        # Left half, on the hinge.
        gl.glPushMatrix()
        gl.glTranslatef(0, 0, L.hinge)
        gl.glRotatef(math.degrees(angle), 0, 1, 0)
        gl.glTranslatef(0, 0, -L.hinge)
        if not self._tex_box(-L.page_w - m, 0, -hy, hy, 0, bm.COVER_T, self._tex_surface.get('front_exterior_image') or self._tex_leather, uv=self._surface_uv('front_exterior_image')):
            self._box(-L.page_w - m, 0, -hy, hy, 0, bm.COVER_T, leather)
        self._endpaper(-L.page_w - m, 0, -hy, hy, endpaper, self._tex_surface.get('front_interior_image') or self._tex_leather, uv=self._surface_uv('front_interior_image'))
        for j in range(L.left_rest_count):
            self._prism(*bm.sheet_slice(L, -1, j, L.left_rest_count), edge)
        if getattr(self, '_has_left_page', True):
            self._sheet(1.0, L.base_left + 0.0015, L.base_left + 0.0015, self._tex_pages['blank'], self._tex_pages['left'])
        # Blender skips its procedural cover tooling when real artwork is supplied, because
        # the artwork already carries the medallion, border and stitching. Match that here or
        # the live view paints old procedural decoration on top of the new cover.
        if not self.book.get('front_exterior_image'):
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

    def _surface_uv(self, field):
        """Framing (sx, sy, ox, oy) for a cover surface, or None when it has no image."""
        aspect = self._surface_aspect.get(field)
        if aspect is None:
            return None
        slot = field[:-6]
        b = self.book
        cover_aspect = self.layout.cover_h / (self.layout.page_w + bm.COVER_MARGIN)
        return bm.fit_uv(aspect, cover_aspect, b.get(f'{slot}_fit', 'fit'),
                         float(b.get(f'{slot}_scale', 1.0)),
                         float(b.get(f'{slot}_x', 0.0)), float(b.get(f'{slot}_y', 0.0)))

    def _tex_box(self, x0, x1, y0, y1, z0, z1, tex, uv=None):
        """A leather-textured box (same shape as _box, grain on every face). False if no texture."""
        if tex is None:
            return False
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glColor3f(1, 1, 1)
        gl.glBegin(gl.GL_QUADS)
        for n, quad in (((0, 0, 1), ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))),
                        ((0, 0, -1), ((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0))),
                        ((0, -1, 0), ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))),
                        ((0, 1, 0), ((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0))),
                        ((1, 0, 0), ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))),
                        ((-1, 0, 0), ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)))):
            gl.glNormal3f(*n)
            for (px, py, pz), (s, t) in zip(quad, ((0, 0), (1, 0), (1, 1), (0, 1))):
                if uv:
                    s = s * uv[0] + uv[2]
                    t = t * uv[1] + uv[3]
                gl.glTexCoord2f(s, t)
                gl.glVertex3f(px, py, pz)
        gl.glEnd()
        gl.glDisable(gl.GL_TEXTURE_2D)
        return True

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

    def _endpaper(self, x0, x1, y0, y1, colour, tex=None, uv=None):
        """Inside-cover (pastedown): leather grain when a texture is loaded, else a flat colour."""
        tex = tex if tex is not None else self._tex_leather
        if tex is not None:
            gl.glEnable(gl.GL_TEXTURE_2D)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glColor3f(1, 1, 1)
        else:
            gl.glDisable(gl.GL_TEXTURE_2D)
            gl.glColor3f(*colour)
        gl.glNormal3f(0, 0, 1)
        gl.glBegin(gl.GL_QUADS)
        for x, y, s, t in ((x0, y0, 0, 0), (x1, y0, 1, 0), (x1, y1, 1, 1), (x0, y1, 0, 1)):
            if uv:
                s = s * uv[0] + uv[2]
                t = t * uv[1] + uv[3]
            gl.glTexCoord2f(s, t)
            gl.glVertex3f(x, y, bm.COVER_T + 0.0006)
        gl.glEnd()
        gl.glDisable(gl.GL_TEXTURE_2D)

    def _sheet(self, t, zr, zl, tex_front, tex_back, key=None, smoothness=1.0):
        L = self.layout
        ck = (key, round(t, 4), zr, zl, round(smoothness, 4))
        if ck not in self._sheet_cache:
            v = sheet_vertices(t, L.page_w, L.page_h, NX, NY, zr, zl,
                               curl=self.values.get('curl', 0.9), gutter=L.gutter,
                               smoothness=smoothness).astype(np.float32)
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
        tex = self._tex_surface.get('spine_exterior_image') or self._tex_leather
        if tex is not None:
            gl.glEnable(gl.GL_TEXTURE_2D)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glColor3f(1, 1, 1)
        else:
            gl.glDisable(gl.GL_TEXTURE_2D)
            gl.glColor3f(*(np.array(colour) * 0.9))
        gl.glBegin(gl.GL_QUADS)
        for face in faces:
            p = v[list(face)]
            nrm = np.cross(p[1] - p[0], p[3] - p[0])
            gl.glNormal3f(*(-nrm / (np.linalg.norm(nrm) + 1e-12)))
            for idx, q in zip(face, p):
                gl.glTexCoord2f((idx % 9) / 8.0, (idx // 9) / 59.0)
                gl.glVertex3f(*q)
        gl.glEnd()
        gl.glDisable(gl.GL_TEXTURE_2D)

    def _hinge(self, angle, colour):
        """The deformable joint skin joining the boards (bends through every opening angle)."""
        verts, faces = bm.hinge_ribbon(self.layout, angle)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glColor3f(*(np.array(colour) * 0.75))
        for face in faces:
            p = verts[list(face)]
            n = np.cross(p[1] - p[0], p[-1] - p[0])
            gl.glBegin(gl.GL_POLYGON)
            gl.glNormal3f(*(n / (np.linalg.norm(n) + 1e-12)))
            for q in p:
                gl.glVertex3f(*q)
            gl.glEnd()

    def _cover_art(self, L):
        """Emblem, title and stitching on the front cover (placed as on the closed book)."""
        if self.book.get('front_exterior_image'):
            return   # supplied artwork already contains its own tooling
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

        # Debossed tooled border: a dark inset frame on the cover face.
        gl.glDisable(gl.GL_LIGHTING)
        gl.glColor3f(*(np.array(_hex_rgb(b.get('leather_color'))) * 0.3))
        gl.glNormal3f(0, 0, -1)
        gl.glLineWidth(2.0)
        for ins in (0.028, 0.046):
            bx0, bx1 = cx - cw / 2 + ins, cx + cw / 2 - ins
            by0, by1 = -ch / 2 + ins, ch / 2 - ins
            gl.glBegin(gl.GL_LINE_LOOP)
            for x, y in ((bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)):
                gl.glVertex3f(*bm.closed_to_open(L, x, y, z_top + 0.0006))
            gl.glEnd()
        gl.glEnable(gl.GL_LIGHTING)



