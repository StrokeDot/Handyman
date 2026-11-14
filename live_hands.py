"""The hands in the live view: meshes baked by hand_bake.py (Blender), bent here frame by frame
with their bones (linear blend skinning in numpy) and drawn with OpenGL, in the book's own space
like the pages. The movement is the render's own (the bake runs the same planning code)."""
import json

import numpy as np

try:
    import OpenGL
    OpenGL.ERROR_CHECKING = False      # (checking every call roughly doubles each call's cost while drawing)
    from OpenGL import GL as gl
except Exception:  # live_view reports a missing OpenGL
    gl = None

SUEDE_RGB = (0.36, 0.23, 0.15)
SLEEVE_TILE_M = 0.09
SHADOW_ALPHA = 0.08      # each of the soft shadow's passes, where the hand touches the page
SHADOW_SOFT = 0.12       # ...each pass also moved sideways this much per unit of the light's shift (a soft edge
                         # even where the hand touches the page, not a sharp dark copy of the fingertips)
SHADOW_FADE = 0.45       # ...gone this high above it (book units: a page is 1 wide)


class _Part:
    def __init__(self, data, key):
        self.pos = np.concatenate([data[key + '_pos'], np.ones((len(data[key + '_pos']), 1), np.float32)], 1)
        self.corner = data[key + '_corner']
        self.uv = np.ascontiguousarray(data[key + '_uv'], np.float32)
        self.bi = data[key + '_bi'].astype(np.int64)
        self.bw = data[key + '_bw'].astype(np.float32)
        self.mats = data[key + '_mats']                     # frames x bones x 4 x 4
        self.tan = data[key + '_tan'] if key + '_tan' in data else None   # (older bakes: none)
        self.ctan = data[key + '_ctan'] if key + '_ctan' in data else None   # per corner (newer bakes)
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
        self._Mv = Mv
        return np.einsum('vij,vj->vi', Mv, self.pos)

    def corner_arrays(self, f):
        key = round(float(f), 3)
        if getattr(self, '_last', (None,))[0] == key:
            self.tangents = self.tangents_last
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
        tan = None
        if self.ctan is not None and len(self.ctan) == len(self.corner):
            # per corner: each side of a picture's seam keeps its own direction
            t = np.einsum('cij,cj->ci', self._Mv[self.corner][:, :, :3], self.ctan[:, :3])
            t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-12
            tan = np.ascontiguousarray(np.concatenate([t, self.ctan[:, 3:4]], 1), np.float32)
        elif self.tan is not None and np.any(self.tan[:, :3]):
            t = np.einsum('vij,vj->vi', self._Mv[:, :, :3], self.tan[:, :3])     # bent with the skin
            t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-12
            tan = np.ascontiguousarray(np.concatenate([t, self.tan[:, 3:4]], 1)[self.corner], np.float32)
        self.tangents = tan
        self._last = (key, *out)
        self.tangents_last = tan
        return out


def _mip_levels(raw):
    """The picture and its halvings down to 1 pixel (box filtered), for mipmapping."""
    out = [raw]
    cur = raw.astype(np.float32)
    while min(cur.shape[0], cur.shape[1]) > 1:
        h, w = cur.shape[0] // 2 * 2, cur.shape[1] // 2 * 2
        cur = cur[:h, :w]
        cur = (cur[0::2, 0::2] + cur[1::2, 0::2] + cur[0::2, 1::2] + cur[1::2, 1::2]) * 0.25
        out.append(np.ascontiguousarray(np.clip(cur + 0.5, 0, 255).astype(np.uint8)))
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

    def _texture(self, path, size=2048):
        """A GL texture for a picture (cached), with mipmaps so fine detail stays smooth and
        clean when the hand is small on screen; None if it cannot be read."""
        if not path:
            return None
        if path in self._tex:
            return self._tex[path]
        tex = None
        try:
            from PIL import Image
            img = Image.open(path).convert('RGB')
            img.thumbnail((size, size))
            raw = np.asarray(img, np.uint8)[::-1].copy()
            tex = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
            levels = _mip_levels(raw)
            for lvl, im in enumerate(levels):
                gl.glTexImage2D(gl.GL_TEXTURE_2D, lvl, gl.GL_RGB, im.shape[1], im.shape[0], 0, gl.GL_RGB,
                                gl.GL_UNSIGNED_BYTE, im)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAX_LEVEL, len(levels) - 1)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
            try:                                                   # sharper at a slant, if offered
                gl.glTexParameterf(gl.GL_TEXTURE_2D, 0x84FE, 8.0)  # GL_TEXTURE_MAX_ANISOTROPY_EXT
            except Exception:
                pass
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
        # darken what is under it (paper stays paper-coloured, only darker; blending a dark
        # colour over it turned yellow paper a dirty grey-green)
        gl.glBlendFunc(gl.GL_DST_COLOR, gl.GL_ZERO)
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
        # (the shadow depends on the hands' pose and the light, not on the camera: worked out once
        # per frame and kept, so turning the view around a still frame only draws it again)
        key = (getattr(self, '_frame_now', None), tuple(id(v) for v in parts), tuple(float(x) for x in sun),
               tuple(np.ravel(z).tolist()) if np.ndim(z) else float(z))
        if getattr(self, '_shadow_key', None) != key:
            self._shadow_key, self._shadow_passes = key, self._shadow_geometry(parts, sun, z)
        for i, pass_ in enumerate(self._shadow_passes):
            gl.glStencilFunc(gl.GL_GREATER, i + 1, 0xFF)
            for p, col in pass_:
                gl.glEnableClientState(gl.GL_COLOR_ARRAY)
                gl.glColorPointer(4, gl.GL_FLOAT, 0, col)
                gl.glVertexPointer(3, gl.GL_FLOAT, 0, p)
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, len(p))
                gl.glDisableClientState(gl.GL_COLOR_ARRAY)
        for i in range(4):
            gl.glDisable(gl.GL_CLIP_PLANE0 + i)
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)   # (as the rest of the view expects)
        gl.glDisable(gl.GL_BLEND)
        gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
        gl.glEnable(gl.GL_LIGHTING)

    @staticmethod
    def _shadow_geometry(parts, sun, z):
        """The shadow's passes: per pass, (projected triangles, their colours) for each hand part."""
        # the light's small shifts (a soft light, not a point): a disc of directions
        jitter = [(0.0, 0.0)] + [(r * np.cos(a), r * np.sin(a)) for r, k in ((0.06, 5), (0.13, 8))
                                 for a in np.linspace(0.0, 2 * np.pi, k, endpoint=False) + r * 7.0]
        passes = []
        for i, (jx, jy) in enumerate(jitter):
            d = sun + np.array((jx, jy, 0.0), np.float32)
            out = []
            for v in parts:
                # onto the page under it: the left and the right side of an open book lie at
                # different heights (z = (height left of the spine, height right of it))
                zi = np.where(v[:, 0:1] < 0.0, z[0], z[1]).astype(np.float32) if np.ndim(z) else np.full((len(v), 1), z, np.float32)
                t = np.maximum(v[:, 2:3] - zi, 0.0) / d[2]          # (a part at the page: right under it)
                p = np.ascontiguousarray(np.concatenate([v[:, :2] - t * d[:2] + np.array((jx, jy), np.float32) * SHADOW_SOFT, zi], 1),
                                         np.float32)
                # dark where the hand is close to the page, fading as it rises (and spreading:
                # the light's small shifts move the high parts' shadow further)
                h = np.maximum(v[:, 2:3] - zi, 0.0)
                alpha = SHADOW_ALPHA * np.clip(1.0 - h / SHADOW_FADE, 0.0, 1.0) ** 1.5
                tint = np.array([[0.42, 0.33, 0.27]], np.float32)       # a warm shadow, as on paper
                rgb = 1.0 - alpha * (1.0 - tint)
                col = np.ascontiguousarray(np.concatenate([rgb, np.ones_like(alpha)], 1), np.float32)
                keep = (v[:, 2:3] > zi - 0.02)[:, 0] & (alpha[:, 0] > 0.002)
                tri_keep = keep.reshape(-1, 3).any(1)
                p = p.reshape(-1, 3, 3)[tri_keep].reshape(-1, 3)
                col = col.reshape(-1, 3, 4)[tri_keep].reshape(-1, 4)
                if len(p):
                    out.append((np.ascontiguousarray(p, np.float32), np.ascontiguousarray(col, np.float32)))
            passes.append(out)
        return passes

    def draw(self, frame, sun=(0.45, -0.55, 0.85), shadow_z=None, shadow_clip=None):
        self._frame_now = round(float(frame), 3)
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
        tan_loc = gl.glGetAttribLocation(prog, 'tangent') if prog else -1
        for h, name, part, v, n in arrays:
            gl.glVertexPointer(3, gl.GL_FLOAT, 0, v)
            gl.glNormalPointer(gl.GL_FLOAT, 0, n)
            uv = part.uv
            photo = False
            nrm = ra = None
            if name == 'skin':
                tex = self._texture(h.get('skin_picture'))
                photo = bool(tex and h.get('skin_is_photo'))
                glove = bool(tex and h.get('skin_is_glove'))
                if glove:                                   # leather gloves made for this hand
                    nrm = self._texture(h.get('skin_normal'))
                    ra = self._texture(h.get('skin_rough_ao'))
                elif tex and not photo:
                    uv = part.uv * 4.0                      # a glove's leather, repeated
                if photo:
                    nrm = self._texture(h.get('skin_normal'))
                    ra = self._texture(h.get('skin_rough_ao'))
                kind = 0 if photo else 2
            else:
                tex = self._texture(h.get('sleeve_picture'))
                nrm = self._texture(h.get('sleeve_normal'), 1024)
                if (tex or nrm) and not h.get('sleeve_uv_native'):
                    uv = part.uv / SLEEVE_TILE_M             # the sleeve's UVs are in metres
                kind = 1
            base = SUEDE_RGB if name == 'sleeve' else (0.78, 0.58, 0.46)
            tans = getattr(part, 'tangents', None)
            use_nrm = bool(prog and nrm and tans is not None and tan_loc >= 0)
            for unit, t in ((1, nrm if use_nrm else None), (2, ra if prog else None)):
                gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
                gl.glBindTexture(gl.GL_TEXTURE_2D, t or 0)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            if tex:
                gl.glEnable(gl.GL_TEXTURE_2D)
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
                gl.glColor3f(1, 1, 1)
            else:
                gl.glDisable(gl.GL_TEXTURE_2D)
                gl.glColor3f(*base)
            if tex or use_nrm:
                gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
                gl.glTexCoordPointer(2, gl.GL_FLOAT, 0, np.ascontiguousarray(uv, np.float32))
            if prog:
                gl.glUseProgram(prog)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'tex'), 0)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'nrmTex'), 1)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'raTex'), 2)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'useTex'), 1 if tex else 0)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'useNrm'), 1 if use_nrm else 0)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'useRA'), 1 if ra and kind in (0, 2) else 0)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'baked'), 1 if h.get('skin_baked') else 0)
                gl.glUniform1i(gl.glGetUniformLocation(prog, 'kind'), kind)
                gl.glUniform3f(gl.glGetUniformLocation(prog, 'base'), *base)
                if use_nrm:
                    gl.glEnableVertexAttribArray(tan_loc)
                    gl.glVertexAttribPointer(tan_loc, 4, gl.GL_FLOAT, gl.GL_FALSE, 0, tans)
                elif tan_loc >= 0:
                    gl.glDisableVertexAttribArray(tan_loc)
                    gl.glVertexAttrib4f(tan_loc, 1.0, 0.0, 0.0, 1.0)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, len(v))
            if prog:
                if use_nrm:
                    gl.glDisableVertexAttribArray(tan_loc)
                gl.glUseProgram(0)
            gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        for unit in (2, 1):
            gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY)


_VERTEX = """
#version 120
attribute vec4 tangent;
varying vec3 vN;
varying vec3 vV;
varying vec3 vObj;
varying vec2 vUV;
varying vec4 vT;
void main() {
    vec4 eye = gl_ModelViewMatrix * gl_Vertex;
    vV = -eye.xyz;
    vN = gl_NormalMatrix * gl_Normal;
    vT = vec4(gl_NormalMatrix * tangent.xyz, tangent.w);
    vObj = gl_Vertex.xyz;
    vUV = gl_MultiTexCoord0.xy;
    gl_ClipVertex = eye;
    gl_Position = gl_ProjectionMatrix * eye;
}
"""

_FRAGMENT = """
#version 120
uniform sampler2D tex;
uniform sampler2D nrmTex;
uniform sampler2D raTex;
uniform int useTex;
uniform int useNrm;
uniform int useRA;
uniform int baked;         // the render's skin baked into the pictures (no extra toning here)
uniform int kind;          // 0 bare skin (photo), 1 sleeve, 2 a glove or other picture
uniform vec3 base;
varying vec3 vN;
varying vec3 vV;
varying vec3 vObj;
varying vec2 vUV;
varying vec4 vT;

float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
float noise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x), mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x), mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

void main() {
    vec3 Ng = normalize(vN);
    vec3 V = normalize(vV);
    float flip = dot(Ng, V) < 0.0 ? -1.0 : 1.0;
    Ng *= flip;
    vec3 N = Ng;
    if (useNrm == 1) {                 // the relief picture (wrinkles, pores / the cloth's weave)
        vec3 t = texture2D(nrmTex, vUV).xyz * 2.0 - 1.0;
        t.xy *= kind == 1 ? 0.6 : 1.0;
        vec3 T = normalize(vT.xyz - Ng * dot(Ng, vT.xyz));
        vec3 B = cross(Ng, T) * vT.w * flip;
        N = normalize(T * t.x + B * t.y + Ng * max(t.z, 0.05));
    }
    vec3 L0 = normalize(gl_LightSource[0].position.xyz);
    vec3 L1 = normalize(gl_LightSource[1].position.xyz);
    vec3 col = useTex == 1 ? texture2D(tex, vUV).rgb : base;
    float ao = 1.0, rough = kind == 1 ? 0.85 : 0.5;
    if (useRA == 1) {
        vec2 ra = texture2D(raTex, vUV).rg;
        ao = mix(1.0, ra.r, 0.85);
        rough = clamp(ra.g, 0.2, 1.0);
    }
    float nv = max(dot(N, V), 0.0);
    vec3 c;
    if (kind == 1) {
        // cloth: broad soft light, a velvety sheen towards the edges, gently mottled
        if (useTex == 0) {             // (no cloth picture: a gentle mottle of its own)
            float m = noise(vObj * 9.0) * 0.6 + noise(vObj * 24.0) * 0.4;
            col *= 0.9 + 0.2 * m;
        }
        float d0 = clamp(dot(N, L0) * 0.7 + 0.3, 0.0, 1.0);
        float d1 = max(dot(N, L1), 0.0);
        float cav = 0.75 + 0.25 * smoothstep(-0.2, 0.6, dot(Ng, L0));   // folds facing away a bit darker
        c = col * (0.30 + 0.80 * d0 * cav + 0.16 * d1);
        c += col * vec3(1.15, 1.0, 0.9) * pow(1.0 - nv, 2.6) * 0.55 * (0.45 + 0.55 * d0);
        vec3 H = normalize(L0 + V);
        c += vec3(0.9, 0.85, 0.8) * pow(max(dot(N, H), 0.0), 12.0) * 0.035;
    } else {
        if (kind == 0 && baked == 0) { // the photo's skin: a touch less orange, as in the render
            float g = dot(col, vec3(0.30, 0.59, 0.11));
            col = mix(vec3(g), col, 0.74) * vec3(0.98, 0.97, 1.0);
        }
        // skin: light wraps round into the shadow side and glows red there (light through skin);
        // creases and between the fingers stay darker (the baked shadowing)
        float w = kind == 0 ? 0.45 : 0.2;
        float nl = dot(N, L0);
        float d0 = max((nl + w) / (1.0 + w), 0.0);
        float d1 = max((dot(N, L1) + w) / (1.0 + w), 0.0);
        float glow = kind == 0 ? smoothstep(-0.5, 0.1, nl) * (1.0 - smoothstep(0.1, 0.65, nl)) : 0.0;
        vec3 diff = 0.27 * ao + 0.86 * d0 * vec3(1.0, 0.97, 0.93) * mix(1.0, ao, 0.45) + 0.22 * d1 * vec3(0.86, 0.9, 1.0) * ao;
        c = col * diff;
        c += col * glow * vec3(0.24, 0.07, 0.04) * ao;
        // a soft sheen, glossier where the skin is smoother (the nails) and at grazing angles
        vec3 H = normalize(L0 + V);
        float nh = max(dot(N, H), 0.0);
        float gloss = 1.0 - rough;
        float sp = pow(nh, mix(8.0, 70.0, gloss)) * mix(0.05, 0.34, gloss * gloss);
        float fres = 0.04 + 0.96 * pow(1.0 - nv, 5.0);
        c += vec3(1.0, 0.96, 0.92) * sp * (0.6 + 1.4 * fres) * step(0.0, nl) * ao;
        c += vec3(0.85, 0.88, 0.95) * pow(1.0 - nv, 3.0) * 0.06 * ao;
    }
    gl_FragColor = vec4(c, 1.0);
}
"""
