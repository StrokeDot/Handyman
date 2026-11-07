"""Live preview of a journal-engine book (OpenGL), drawn from journal_geom.

The final render (journal_scene.py) and this preview take every shape from the same
functions - sheets, cover hinge, spine, camera - so what you see while editing is the book
that gets rendered. Only the lighting and materials are simpler here.
"""
import math

import numpy as np

import cover_shape
import journal_geom as G

try:
    from OpenGL import GL as gl
except Exception:  # the caller (live_view) already reports a missing OpenGL
    gl = None


def _faces(rows, cols):
    """Triangles of a rows x cols grid, plus the rim of the solid sheet (top + bottom layers)."""
    idx = lambda i, k: i * cols + k  # noqa: E731
    top = []
    for i in range(rows - 1):
        for k in range(cols - 1):
            a, b, c, d = idx(i, k), idx(i, k + 1), idx(i + 1, k + 1), idx(i + 1, k)
            top += [a, b, c, a, c, d]
    nv = rows * cols
    bottom = [nv + x for tri in zip(top[0::3], top[2::3], top[1::3]) for x in tri]   # reversed winding
    ring = ([idx(0, k) for k in range(cols)] + [idx(i, cols - 1) for i in range(1, rows)] +
            [idx(rows - 1, k) for k in range(cols - 2, -1, -1)] + [idx(i, 0) for i in range(rows - 2, 0, -1)])
    rim = []
    for m in range(len(ring)):
        a, b = ring[m], ring[(m + 1) % len(ring)]
        rim += [a, nv + a, nv + b, a, nv + b, b]
    return (np.array(top, np.uint32), np.array(bottom, np.uint32), np.array(rim, np.uint32))


def _normals(v, tris):
    n = np.zeros_like(v)
    t = tris.reshape(-1, 3)
    fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    for c in range(3):
        np.add.at(n, t[:, c], fn)
    return (n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)).astype(np.float32)


class JournalPreview:
    """Holds cached meshes; draw() paints one frame with the current GL matrices."""

    def __init__(self, book, page_count, page_shape='flat', turn_style='natural'):
        G.configure(int(page_count or book.get('page_count') or 10), float(book.get('page_aspect', 1.4318)),
                    cover=G.cover_of(book),
                    page_shape=page_shape, turn_style=turn_style)
        self.rows = len(G.rows(G.NY))
        self.cols = G.NX
        self.top, self.bottom, self.rim = _faces(self.rows, self.cols)
        uv = G.sheet_uvs(G.NY).astype(np.float32)
        uv_back = uv.copy()
        uv_back[:, 0] = 1.0 - uv_back[:, 0]
        pad = np.zeros_like(uv)
        self.uv_front = np.concatenate([uv, pad]).astype(np.float32)
        self.uv_back = np.concatenate([pad, uv_back]).astype(np.float32)
        self._cache = {}
        # the boards' fore-edge corners are cut as round as the cover picture's own corners
        import templates
        self.corner = cover_shape.corner_radius(templates._texture_path(book, book.get('front_exterior_image')))
        # which winding faces outwards: the top face's first triangle against the sheet's up direction
        v = G.solid_from_grid(G.sheet_state(0, 0.0, 0.0))
        t = self.top[:3]
        n = np.cross(v[t[1]] - v[t[0]], v[t[2]] - v[t[0]])
        self.front_face = gl.GL_CCW if (gl is None or n[2] > 0) else gl.GL_CW

    # ------------------------------------------------------------------ meshes
    def sheet(self, k, t, curve=1.0):
        key = (k, round(float(t), 4), round(G.OPEN_W, 4), round(G.OPEN_B, 4), round(float(curve), 4),
               round(G.TURNED, 4))
        hit = self._cache.get(key)
        if hit is None:
            if len(self._cache) > 600:      # make room first: clearing after storing lost this sheet
                self._cache.clear()         # and stopped the drawing halfway (the book disappeared)
            v = G.solid_from_grid(G.sheet_state(k, t, curve)).astype(np.float32)
            n = _normals(v, np.concatenate([self.top, self.bottom]))
            hit = self._cache[key] = (v, n)
        return hit

    # ------------------------------------------------------------------ drawing
    def draw(self, pose, tex, leather_rgb, paper_rgb):
        """tex: {'front_ext','back_ext','front_in','back_in','spine', ('page', i) or 'paper_odd'/'paper_even'}."""
        theta = G.cover_angle(float(pose['cover_progress']))
        G.set_opening(theta)          # pages flat while closed, curved once the cover lifts off them
        slide = float(pose.get('cover_slide', 0.0))
        gl.glPushMatrix()
        try:
            self._draw(theta, slide, pose, tex, leather_rgb, paper_rgb)
        finally:
            gl.glPopMatrix()

    def _draw(self, theta, slide, pose, tex, leather_rgb, paper_rgb):
        gl.glTranslatef(slide, 0, 0)
        self._board(G.XB, tex.get('back_in'), tex.get('back_ext'), leather_rgb)
        gl.glPushMatrix()
        pv = G.cover_pivot(theta)
        gl.glTranslatef(float(pv[0]), 0.0, float(pv[1]))
        gl.glRotatef(math.degrees(-theta), 0, 1, 0)
        self._board(0.0, tex.get('front_ext'), tex.get('front_in'), leather_rgb)
        gl.glPopMatrix()
        self._spine(theta, tex.get('spine'), leather_rgb)
        edge = tuple(np.array(paper_rgb) * 0.78)
        prog = pose['sheet_progress']
        ts = [float(prog[k]) if k < len(prog) else 0.0 for k in range(G.N_SHEETS)]
        cw = G.curve_weights(ts)          # only the visible spread is curved; pages under it are flat
        G.set_turned(ts)                  # the spine's crest sits between the turned and unturned pages
        for k in range(G.N_SHEETS):
            front = tex.get(('page', 2 * k)) or tex.get('paper_odd')
            back = tex.get(('page', 2 * k + 1)) or tex.get('paper_even')
            self._sheet(k, ts[k], front, back, edge, cw[k])

    def _outline(self, x0):
        """Board outline: straight along the spine (x0), fore-edge corners rounded like the art."""
        x1, hy = x0 + G.WC, G.HC / 2
        rad = min(self.corner * G.WC, 0.3)
        pts = [(x0, -hy)]
        for k in range(9):                         # bottom fore-edge corner
            a = -math.pi / 2 + k * (math.pi / 2) / 8
            pts.append((x1 - rad + rad * math.cos(a), -hy + rad + rad * math.sin(a)))
        for k in range(9):                         # top fore-edge corner
            a = k * (math.pi / 2) / 8
            pts.append((x1 - rad + rad * math.cos(a), hy - rad + rad * math.sin(a)))
        pts.append((x0, hy))
        return pts

    def _board(self, x0, tex_top, tex_bottom, colour):
        """A cover board in its own frame: x x0..x0+WC, y +-HC/2, z 0..TB, with the cover art's
        rounded fore-edge corners. tex_top on z = TB, tex_bottom on z = 0 (as the Blender board's
        two caps; the bottom one mirrored, as it is seen from below)."""
        hy, z1 = G.HC / 2, G.TB
        pts = self._outline(x0)
        cx = x0 + G.WC / 2
        for z, tex, nz in ((z1, tex_top, 1.0), (0.0, tex_bottom, -1.0)):
            if tex:
                gl.glEnable(gl.GL_TEXTURE_2D)
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
                gl.glColor3f(1, 1, 1)
            else:
                gl.glDisable(gl.GL_TEXTURE_2D)
                gl.glColor3f(*colour)
            gl.glNormal3f(0, 0, nz)
            ring = pts if nz > 0 else pts[::-1]
            gl.glBegin(gl.GL_TRIANGLE_FAN)
            for x, y in [(cx, 0.0)] + ring + [ring[0]]:
                s_ = (x - x0) / G.WC
                gl.glTexCoord2f(s_ if nz > 0 else 1 - s_, (y + hy) / (2 * hy))
                gl.glVertex3f(x, y, z)
            gl.glEnd()
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glColor3f(*(np.array(colour) * 0.8))
        gl.glBegin(gl.GL_QUADS)
        for (xa, ya), (xb, yb) in zip(pts, pts[1:] + pts[:1]):
            nx_, ny_ = yb - ya, -(xb - xa)
            ln = math.hypot(nx_, ny_) or 1.0
            gl.glNormal3f(nx_ / ln, ny_ / ln, 0.0)
            for x, y, z in ((xa, ya, 0.0), (xb, yb, 0.0), (xb, yb, z1), (xa, ya, z1)):
                gl.glVertex3f(x, y, z)
        gl.glEnd()

    def _spine(self, theta, tex, colour):
        c = G.spine_curve(theta, 24)
        hy = G.HC / 2
        if tex:
            gl.glEnable(gl.GL_TEXTURE_2D)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glColor3f(1, 1, 1)
        else:
            gl.glDisable(gl.GL_TEXTURE_2D)
            gl.glColor3f(*colour)
        gl.glBegin(gl.GL_QUADS)
        n = len(c)
        for i in range(n - 1):
            (xa, za), (xb, zb) = c[i], c[i + 1]
            tx, tz = xb - xa, zb - za
            gl.glNormal3f(tz, 0, -tx)
            for x, y, z, s, t in ((xa, -hy, za, i / (n - 1), 0), (xb, -hy, zb, (i + 1) / (n - 1), 0),
                                  (xb, hy, zb, (i + 1) / (n - 1), 1), (xa, hy, za, i / (n - 1), 1)):
                gl.glTexCoord2f(s, t)
                gl.glVertex3f(x, y, z)
        gl.glEnd()
        gl.glDisable(gl.GL_TEXTURE_2D)

    def _sheet(self, k, t, tex_front, tex_back, edge, curve=1.0):
        v, n = self.sheet(k, t, curve)
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
        gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
        gl.glVertexPointer(3, gl.GL_FLOAT, 0, v)
        gl.glNormalPointer(gl.GL_FLOAT, 0, n)
        gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        # A sheet is thinner than the depth buffer can tell apart from far away, so its two faces
        # fought and the back page's ink showed through the front. Draw only the face turned to us.
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glCullFace(gl.GL_BACK)
        gl.glFrontFace(self.front_face)
        for tris, tex, uv in ((self.top, tex_front, self.uv_front), (self.bottom, tex_back, self.uv_back)):
            if tex:
                gl.glEnable(gl.GL_TEXTURE_2D)
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
                gl.glColor3f(1, 1, 1)
            else:
                gl.glDisable(gl.GL_TEXTURE_2D)
                gl.glColor3f(0.9, 0.82, 0.66)
            gl.glTexCoordPointer(2, gl.GL_FLOAT, 0, uv)
            gl.glDrawElements(gl.GL_TRIANGLES, len(tris), gl.GL_UNSIGNED_INT, tris)
        gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glFrontFace(gl.GL_CCW)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glColor3f(*edge)
        gl.glDrawElements(gl.GL_TRIANGLES, len(self.rim), gl.GL_UNSIGNED_INT, self.rim)
        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY)
