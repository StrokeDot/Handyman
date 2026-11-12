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

    # ------------------------------------------------------------ shading
    def _program(self):
        """The hands' shading (compiled once): light glowing through the skin near the shadow
        line, a soft skin shine, suede's velvety edge sheen and mottled nap. None if this
        computer's OpenGL cannot compile it (then the plain lighting is used)."""
        if getattr(self, '_prog_tried', False):
            return self._prog
        self._prog_tried, self._prog = True, None
        try:
            from OpenGL.GL import shaders
            vs = shaders.compileShader(_VERTEX, gl.GL_VERTEX_SHADER)
            fs = shaders.compileShader(_FRAGMENT, gl.GL_FRAGMENT_SHADER)
            self._prog = shaders.compileProgram(vs, fs, validate=False)
        except Exception:
            self._prog = None
        return self._prog

    def _shadow(self, parts, sun, z, clip):
        """A soft shadow of the hands on the book (the light straight down its direction onto a
        plane just over the pages), drawn a few times with the light slightly moved."""
        sun = np.asarray(sun, np.float32)
        sun = sun / np.linalg.norm(sun)
        gl.glDisable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY)
        if clip is not None:                                       # only on the book (held up: no table)
            x0, x1, y0, y1 = clip
            for i, eq in enumerate(((1, 0, 0, -x0), (-1, 0, 0, x1), (0, 1, 0, -y0), (0, -1, 0, y1))):
                gl.glClipPlane(gl.GL_CLIP_PLANE0 + i, eq)
                gl.glEnable(gl.GL_CLIP_PLANE0 + i)
        # each pass darkens a spot only once, however many bits of hand overlap there (stencil)
        gl.glClear(gl.GL_STENCIL_BUFFER_BIT)
        gl.glEnable(gl.GL_STENCIL_TEST)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_REPLACE)
        gl.glDepthMask(gl.GL_FALSE)
        jitter = ((0, 0), (0.08, 0.03), (-0.06, 0.07), (0.04, -0.08), (-0.09, -0.03), (0.02, 0.1))
        for i, (jx, jy) in enumerate(jitter):
            d = sun + np.array((jx, jy, 0.0), np.float32)
            gl.glStencilFunc(gl.GL_GREATER, i + 1, 0xFF)
            gl.glColor4f(0.07, 0.05, 0.04, 0.055)
            for v in parts:
                # onto the page under it: the left and the right side of an open book lie at
                # different heights (z = (height left of the spine, height right of it))
                zi = np.where(v[:, 0:1] < 0.0, z[0], z[1]).astype(np.float32) if np.ndim(z) else np.full((len(v), 1), z, np.float32)
                t = (v[:, 2:3] - zi) / d[2]
                p = np.ascontiguousarray(np.concatenate([v[:, :2] - t * d[:2], zi], 1), np.float32)
                keep = (v[:, 2:3] > zi - 0.02)[:, 0]               # (nothing below the page casts on it)
                if not keep.all():
                    p = p.reshape(-1, 3, 3)[keep.reshape(-1, 3).all(1)].reshape(-1, 3)
                if len(p):
                    gl.glVertexPointer(3, gl.GL_FLOAT, 0, p)
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, len(p))
        for i in range(4):
            gl.glDisable(gl.GL_CLIP_PLANE0 + i)
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
        gl.glEnable(gl.GL_LIGHTING)

    def draw(self, frame, sun=(0.45, -0.55, 0.85), shadow_z=None, shadow_clip=None):
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
        gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
        gl.glDisable(gl.GL_CULL_FACE)
        arrays = [(h, name, part, *part.corner_arrays(frame)) for h in self.hands for name, part in h['parts'].items()]
        if shadow_z is not None:
            try:
                self._shadow([a[3] for a in arrays], sun, shadow_z, shadow_clip)
            except Exception:
                pass
        prog = self._program()
        for h, name, part, v, n in arrays:
            gl.glVertexPointer(3, gl.GL_FLOAT, 0, v)
            gl.glNormalPointer(gl.GL_FLOAT, 0, n)
            uv = part.uv
            photo = False
            if name == 'skin':
                tex = self._texture(h.get('skin_picture'))
                photo = bool(tex and h.get('skin_is_photo'))
                if tex and not photo:
                    uv = part.uv * 4.0                      # a glove's leather, repeated
            else:
                tex = self._texture(h.get('sleeve_picture'))
                if tex:
                    uv = part.uv / SLEEVE_TILE_M             # the sleeve's UVs are in metres
            base = SUEDE_RGB if name == 'sleeve' else (0.78, 0.58, 0.46)
            if tex:
                gl.glEnable(gl.GL_TEXTURE_2D)
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
                gl.glColor3f(1, 1, 1)
                gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
                gl.glTexCoordPointer(2, gl.GL_FLOAT, 0, np.ascontiguousarray(uv, np.float32))
            else:
                gl.glDisable(gl.GL_TEXTURE_2D)
                gl.glColor3f(*base)
            if prog:
                gl.glUseProgram(prog)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'tex'), 0)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'useTex'), 1 if tex else 0)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'kind'), 1 if name == 'sleeve' else (2 if tex and not photo else 0))
                gl.glUniform3f(gl.glGetUniformLocation(prog, 'base'), *base)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, len(v))
            if prog:
                gl.glUseProgram(0)
            gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY)


_VERTEX = """
#version 120
varying vec3 vN;
varying vec3 vV;
varying vec3 vObj;
varying vec2 vUV;
void main() {
    vec4 eye = gl_ModelViewMatrix * gl_Vertex;
    vV = -eye.xyz;
    vN = gl_NormalMatrix * gl_Normal;
    vObj = gl_Vertex.xyz;
    vUV = gl_MultiTexCoord0.xy;
    gl_ClipVertex = eye;
    gl_Position = gl_ProjectionMatrix * eye;
}
"""

_FRAGMENT = """
#version 120
uniform sampler2D tex;
uniform int useTex;
uniform int kind;          // 0 bare skin (photo), 1 sleeve, 2 a glove or other picture
uniform vec3 base;
varying vec3 vN;
varying vec3 vV;
varying vec3 vObj;
varying vec2 vUV;

float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
float noise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x), mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x), mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

void main() {
    vec3 N = normalize(vN);
    vec3 V = normalize(vV);
    if (dot(N, V) < 0.0) N = -N;
    vec3 L0 = normalize(gl_LightSource[0].position.xyz);
    vec3 L1 = normalize(gl_LightSource[1].position.xyz);
    vec3 col = useTex == 1 ? texture2D(tex, vUV).rgb : base;
    float nv = max(dot(N, V), 0.0);
    vec3 c;
    if (kind == 1) {
        // suede: mottled nap, soft broad light, a velvety sheen towards the edges
        float m = noise(vObj * 9.0) * 0.6 + noise(vObj * 24.0) * 0.4;
        col *= 0.84 + 0.3 * m;
        float d0 = clamp(dot(N, L0) * 0.75 + 0.25, 0.0, 1.0);
        float d1 = max(dot(N, L1), 0.0);
        c = col * (0.34 + 0.78 * d0 + 0.18 * d1);
        c += vec3(0.80, 0.66, 0.52) * pow(1.0 - nv, 2.4) * 0.34 * (0.4 + 0.6 * d0);
    } else {
        if (kind == 0) {               // the photo's skin: a touch less orange, as in the render
            float g = dot(col, vec3(0.30, 0.59, 0.11));
            col = mix(vec3(g), col, 0.74) * vec3(0.98, 0.97, 1.0);
        }
        // light wraps round into the shadow side and glows red there, as through skin
        float w = kind == 0 ? 0.5 : 0.2;
        float nl = dot(N, L0);
        float d0 = max((nl + w) / (1.0 + w), 0.0);
        float d1 = max((dot(N, L1) + w) / (1.0 + w), 0.0);
        float glow = kind == 0 ? smoothstep(-0.45, 0.15, nl) * (1.0 - smoothstep(0.15, 0.7, nl)) : 0.0;
        c = col * (0.30 + 0.80 * d0 * vec3(1.0, 0.98, 0.95) + 0.24 * d1 * vec3(0.85, 0.9, 1.0));
        c += col * glow * vec3(0.20, 0.05, 0.03);
        vec3 H = normalize(L0 + V);
        float nh = max(dot(N, H), 0.0);
        c += vec3(1.0, 0.95, 0.9) * (pow(nh, 30.0) * 0.16 + pow(nh, 7.0) * 0.05) * step(0.0, nl);
        c += vec3(0.9, 0.9, 0.95) * pow(1.0 - nv, 3.0) * 0.05;
    }
    gl_FragColor = vec4(c, 1.0);
}
"""
