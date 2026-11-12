"""The hands in the live view: meshes baked by hand_bake.py (Blender), bent here frame by frame
with their bones (linear blend skinning in numpy) and drawn with OpenGL, in the book's own space
like the pages. The movement is the render's own (the bake runs the same planning code)."""
import json

import numpy as np

try:
    from OpenGL import GL as gl
except Exception:  # live_view reports a missing OpenGL
    gl = None

SUEDE_RGB = (0.36, 0.23, 0.15)
SLEEVE_TILE_M = 0.09


class _Part:
    def __init__(self, data, key):
        self.pos = np.concatenate([data[key + '_pos'], np.ones((len(data[key + '_pos']), 1), np.float32)], 1)
        self.corner = data[key + '_corner']
        self.uv = np.ascontiguousarray(data[key + '_uv'], np.float32)
        self.bi = data[key + '_bi'].astype(np.int64)
        self.bw = data[key + '_bw'].astype(np.float32)
        self.mats = data[key + '_mats']                     # frames x bones x 4 x 4
        self.idx = np.arange(len(self.corner), dtype=np.uint32)
        t = self.corner.reshape(-1, 3)
        self.tris = t

    def posed(self, f):
        """Vertex positions (book space) at a frame (fractional frames blend the bones)."""
        n = len(self.mats)
        f = min(max(float(f), 0.0), n - 1.0)
        a = int(f)
        b = min(a + 1, n - 1)
        w = f - a
        M = (self.mats[a] * (1 - w) + self.mats[b] * w if w > 1e-6 else self.mats[a])[:, :3, :]
        # each vertex: its bones' matrices blended by weight, applied to its rest position
        Mv = self.bw[:, 0, None, None] * M[self.bi[:, 0]]
        for k in range(1, self.bi.shape[1]):
            Mv += self.bw[:, k, None, None] * M[self.bi[:, k]]
        return np.einsum('vij,vj->vi', Mv, self.pos)

    def corner_arrays(self, f):
        key = round(float(f), 3)
        if getattr(self, '_last', (None,))[0] == key:
            return self._last[1], self._last[2]
        v = self.posed(f)
        t = self.tris
        fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        nv = len(v)
        n = np.empty_like(v)
        for ax in range(3):
            n[:, ax] = (np.bincount(t[:, 0], fn[:, ax], nv) + np.bincount(t[:, 1], fn[:, ax], nv) +
                        np.bincount(t[:, 2], fn[:, ax], nv))
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        out = (np.ascontiguousarray(v[self.corner], np.float32), np.ascontiguousarray(n[self.corner], np.float32))
        self._last = (key, *out)
        return out


class LiveHands:
    """Loaded from a bake file; draw(frame) paints both hands with the current GL matrices."""

    def __init__(self, path):
        data = np.load(path)
        self.meta = json.loads(bytes(data['meta']).decode('utf-8'))
        self.frames = int(self.meta['frames'])
        self.hands = []
        for h in self.meta['hands']:
            parts = {key.split('_', 1)[1]: _Part(data, key) for key in h['parts']}
            self.hands.append(dict(h, parts=parts))
        self._tex = {}

    def _texture(self, path):
        """A GL texture for a picture (cached); None if it cannot be read."""
        if not path:
            return None
        if path in self._tex:
            return self._tex[path]
        tex = None
        try:
            from PIL import Image
            img = Image.open(path).convert('RGB')
            img.thumbnail((1024, 1024))
            raw = np.asarray(img, np.uint8)[::-1].copy()
            tex = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, raw.shape[1], raw.shape[0], 0, gl.GL_RGB,
                            gl.GL_UNSIGNED_BYTE, raw)
        except Exception:
            tex = None
        self._tex[path] = tex
        return tex

    def release(self):
        for tex in self._tex.values():
            if tex:
                try:
                    gl.glDeleteTextures([tex])
                except Exception:
                    pass
        self._tex = {}

    def draw(self, frame):
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
        gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
        gl.glDisable(gl.GL_CULL_FACE)
        for h in self.hands:
            for name, part in h['parts'].items():
                v, n = part.corner_arrays(frame)
                gl.glVertexPointer(3, gl.GL_FLOAT, 0, v)
                gl.glNormalPointer(gl.GL_FLOAT, 0, n)
                uv = part.uv
                if name == 'skin':
                    tex = self._texture(h.get('skin_picture'))
                    if tex and not h.get('skin_is_photo'):
                        uv = part.uv * 4.0                      # a glove's leather, repeated
                else:
                    tex = self._texture(h.get('sleeve_picture'))
                    if tex:
                        uv = part.uv / SLEEVE_TILE_M             # the sleeve's UVs are in metres
                if tex:
                    gl.glEnable(gl.GL_TEXTURE_2D)
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
                    gl.glColor3f(1, 1, 1)
                    gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
                    gl.glTexCoordPointer(2, gl.GL_FLOAT, 0, np.ascontiguousarray(uv, np.float32))
                else:
                    gl.glDisable(gl.GL_TEXTURE_2D)
                    gl.glColor3f(*(SUEDE_RGB if name == 'sleeve' else (0.78, 0.58, 0.46)))
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, len(v))
                gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY)
