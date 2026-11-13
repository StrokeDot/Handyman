"""Journal engine: builds a real-page book from a template inside Blender and renders
transparent PNG frames. Same job file and progress lines as book_scene.py; the app picks this
script when the template says "engine": "journal".

    blender -b --factory-startup -P journal_scene.py -- job.json

Geometry and motion come from journal_geom.py (pure numpy): every sheet is a real solid sheet
cut to the page outline, paper never stretches, the bound edge rolls as pages land, and every
landed page is kept above the open cover along its whole width.
"""
import json
import math
import os
import shutil
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal_geom as G  # noqa: E402
import scene  # noqa: E402
from book_scene import setup_render, log  # noqa: E402
from page_curl import layout_pages  # noqa: E402


def image(p):
    p = os.path.abspath(p)
    for im in bpy.data.images:
        if im.filepath == p:
            return im
    return bpy.data.images.load(p)


def principled(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return nt, bsdf, out


def image_material(name, img_path, roughness=0.55, bump=0.0, bump_dist=0.003, alpha=False,
                   translucent=0.0, spec=0.5):
    mat = bpy.data.materials.new(name)
    nt, bsdf, out = principled(mat)
    tx = nt.nodes.new('ShaderNodeTexImage')
    tx.image = image(img_path)
    tx.interpolation = 'Cubic'
    tx.extension = 'EXTEND'
    nt.links.new(tx.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Specular IOR Level'].default_value = spec
    if alpha:
        nt.links.new(tx.outputs['Alpha'], bsdf.inputs['Alpha'])
    if bump > 0:
        bw = nt.nodes.new('ShaderNodeRGBToBW')
        nt.links.new(tx.outputs['Color'], bw.inputs['Color'])
        bp = nt.nodes.new('ShaderNodeBump')
        bp.inputs['Strength'].default_value = bump
        bp.inputs['Distance'].default_value = bump_dist
        nt.links.new(bw.outputs['Val'], bp.inputs['Height'])
        nt.links.new(bp.outputs['Normal'], bsdf.inputs['Normal'])
    if translucent > 0:
        tr = nt.nodes.new('ShaderNodeBsdfTranslucent')
        nt.links.new(tx.outputs['Color'], tr.inputs['Color'])
        mix = nt.nodes.new('ShaderNodeMixShader')
        mix.inputs['Fac'].default_value = translucent
        nt.links.new(bsdf.outputs['BSDF'], mix.inputs[1])
        nt.links.new(tr.outputs['BSDF'], mix.inputs[2])
        nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    return mat


def _darken(mat, k):
    nt = mat.node_tree
    tx = [n for n in nt.nodes if n.type == 'TEX_IMAGE'][0]
    bsdf = [n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'][0]
    mul = nt.nodes.new('ShaderNodeMix')
    mul.data_type = 'RGBA'
    mul.blend_type = 'MULTIPLY'
    mul.inputs['Factor'].default_value = 1.0
    mul.inputs['B'].default_value = (k, k, k, 1)
    nt.links.new(tx.outputs['Color'], mul.inputs['A'])
    nt.links.new(mul.outputs['Result'], bsdf.inputs['Base Color'])


def color_material(name, rgb, roughness=0.8, noise=0.0):
    mat = bpy.data.materials.new(name)
    nt, bsdf, out = principled(mat)
    bsdf.inputs['Base Color'].default_value = (*rgb, 1.0)
    bsdf.inputs['Roughness'].default_value = roughness
    if noise > 0:
        nz = nt.nodes.new('ShaderNodeTexNoise')
        nz.inputs['Scale'].default_value = 60.0
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = tuple(c * (1 - noise) for c in rgb) + (1.0,)
        ramp.color_ramp.elements[1].color = (*rgb, 1.0)
        nt.links.new(nz.outputs['Fac'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    return mat


def new_object(name, mesh, parent=None):
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    if parent:
        ob.parent = parent
    return ob


def page_edge_material():
    """Stacked paper seen edge-on: fine sheet lines plus mottled ageing."""
    mat = bpy.data.materials.new('PageEdge')
    nt, bsdf, out = principled(mat)
    tc = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(tc.outputs['Object'], sep.inputs['Vector'])
    wave = nt.nodes.new('ShaderNodeTexWave')
    wave.wave_type = 'BANDS'
    wave.bands_direction = 'Z'
    wave.inputs['Scale'].default_value = 1.0 / (2 * G.PITCH) / 4.0
    wave.inputs['Distortion'].default_value = 2.0
    wave.inputs['Detail'].default_value = 2.0
    nt.links.new(tc.outputs['Object'], wave.inputs['Vector'])
    nz = nt.nodes.new('ShaderNodeTexNoise')
    nz.inputs['Scale'].default_value = 25.0
    nt.links.new(tc.outputs['Object'], nz.inputs['Vector'])
    lines = nt.nodes.new('ShaderNodeValToRGB')
    lines.color_ramp.elements[0].position = 0.35
    lines.color_ramp.elements[0].color = (0.66, 0.36, 0.12, 1)
    lines.color_ramp.elements[1].position = 0.75
    lines.color_ramp.elements[1].color = (0.92, 0.58, 0.24, 1)
    nt.links.new(wave.outputs['Fac'], lines.inputs['Fac'])
    age = nt.nodes.new('ShaderNodeValToRGB')
    age.color_ramp.elements[0].color = (0.86, 0.62, 0.38, 1)
    age.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1)
    nt.links.new(nz.outputs['Fac'], age.inputs['Fac'])
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs['Factor'].default_value = 1.0
    nt.links.new(lines.outputs['Color'], mix.inputs['A'])
    nt.links.new(age.outputs['Color'], mix.inputs['B'])
    nt.links.new(mix.outputs['Result'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.95
    bsdf.inputs['Specular IOR Level'].default_value = 0.05   # paper edges: no cool sheen
    return mat


# ---- sheets ------------------------------------------------------------------------------
def solid_from_grid(mid, thick):
    """Top/bottom vertices of a solid sheet from its mid-surface grid (ny, nx, 3)."""
    dx = np.gradient(mid, axis=1)
    dy = np.gradient(mid, axis=0)
    nrm = np.cross(dx, dy)
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True) + 1e-12
    top = mid + nrm * thick / 2
    bot = mid - nrm * thick / 2
    return np.concatenate([top.reshape(-1, 3), bot.reshape(-1, 3)])


def sheet_mesh(name, n_mid, nx):
    """Topology of a solid sheet: top face grid, bottom face grid, rim. UVs per face.
    Rows follow G.rows and are trimmed at the rounded corners, so the picture is cut exactly
    where the paper is cut."""
    vv = G.rows(n_mid)
    ny = len(vv)
    U = [[k / (nx - 1) * G.smax(vv[i]) / G.W for k in range(nx)] for i in range(ny)]
    nv = ny * nx
    idx = lambda i, k: i * nx + k
    faces, mats, uvs = [], [], []
    for i in range(ny - 1):
        for k in range(nx - 1):
            a, b, c, d = idx(i, k), idx(i, k + 1), idx(i + 1, k + 1), idx(i + 1, k)
            pa, pb = (U[i][k], vv[i]), (U[i][k + 1], vv[i])
            pc, pd = (U[i + 1][k + 1], vv[i + 1]), (U[i + 1][k], vv[i + 1])
            faces.append((a, b, c, d))                          # top (front of the sheet)
            mats.append(0)
            uvs.append([pa, pb, pc, pd])
            faces.append((nv + d, nv + c, nv + b, nv + a))      # bottom (back of the sheet)
            mats.append(1)
            uvs.append([(1 - q[0], q[1]) for q in (pd, pc, pb, pa)])
    ring = [idx(0, k) for k in range(nx)] + [idx(i, nx - 1) for i in range(1, ny)] + \
           [idx(ny - 1, k) for k in range(nx - 2, -1, -1)] + [idx(i, 0) for i in range(ny - 2, 0, -1)]
    for m in range(len(ring)):
        a, b = ring[m], ring[(m + 1) % len(ring)]
        faces.append((a, nv + a, nv + b, b))
        mats.append(2)
        uvs.append([(0, 0), (0, 1), (1, 1), (1, 0)])
    me = bpy.data.meshes.new(name)
    me.from_pydata([(0, 0, 0)] * (2 * nv), [], faces)
    me.polygons.foreach_set('material_index', mats)
    me.polygons.foreach_set('use_smooth', [m != 2 for m in mats])
    uv = me.uv_layers.new(name='UVMap')
    flat = [c for f in uvs for v in f for c in v]
    uv.data.foreach_set('uv', flat)
    return me


def set_coords(me, co):
    me.vertices.foreach_set('co', np.asarray(co, np.float32).ravel())
    me.update()


def add_shape_frames(ob, coords_by_frame, rest_after=None):
    """Store per-frame coordinates as shape keys, keyframed so exactly one is active per frame
    (linear blending between neighbours gives correct motion blur)."""
    if ob.data.shape_keys is None:
        ob.shape_key_add(name='Basis', from_mix=False)
    frames = sorted(coords_by_frame)
    keys = []
    for f in frames:
        kb = ob.shape_key_add(name=f'f{f}', from_mix=False)
        kb.data.foreach_set('co', np.asarray(coords_by_frame[f], np.float32).ravel())
        keys.append((f, kb))
    for n, (f, kb) in enumerate(keys):
        kb.value = 0.0
        kb.keyframe_insert('value', frame=f - 1)
        kb.value = 1.0
        kb.keyframe_insert('value', frame=f)
        if n < len(keys) - 1:          # the last key stays on (the resting pose after the motion)
            kb.value = 0.0
            kb.keyframe_insert('value', frame=f + 1)
    ad = ob.data.shape_keys.animation_data
    if ad and ad.action:
        for fc in ad.action.fcurves if hasattr(ad.action, 'fcurves') else []:
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'
    _linear_all(ob.data.shape_keys)


def _linear_all(idblock):
    ad = idblock.animation_data
    if not ad or not ad.action:
        return
    act = ad.action
    curves = []
    if hasattr(act, 'fcurves') and len(getattr(act, 'fcurves', [])):
        curves = act.fcurves
    else:   # Blender 5 layered actions
        for layer in act.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    curves.extend(bag.fcurves)
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'


# ---- board -------------------------------------------------------------------------------
def board_mesh(name, rad=0.035, seg=6):
    """Board in local space: x 0..WC (spine edge at 0), y -HC/2..HC/2, z 0..TB.
    Material 0 = top cap, 1 = bottom cap, 2 = edges. Fore-edge corners rounded."""
    wc, hh = G.WC, G.HC / 2
    pts = [(0.0, -hh)]
    for k in range(seg + 1):                        # bottom fore-edge corner
        a = -math.pi / 2 + k * (math.pi / 2) / seg
        pts.append((wc - rad + rad * math.cos(a), -hh + rad + rad * math.sin(a)))
    for k in range(seg + 1):                        # top fore-edge corner
        a = k * (math.pi / 2) / seg
        pts.append((wc - rad + rad * math.cos(a), hh - rad + rad * math.sin(a)))
    pts.append((0.0, hh))
    n = len(pts)
    verts = [(x, y, 0.0) for x, y in pts] + [(x, y, G.TB) for x, y in pts]
    faces = [tuple(range(n, 2 * n)), tuple(range(n - 1, -1, -1))]
    mats = [0, 1]
    for k in range(n):
        a, b = k, (k + 1) % n
        faces.append((a, b, n + b, n + a))
        mats.append(2)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.polygons.foreach_set('material_index', mats)
    uv = me.uv_layers.new(name='UVMap')
    data = []
    for p, m in zip(me.polygons, mats):
        for li in p.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            if m == 0:
                data += [v.x / wc, (v.y + hh) / (2 * hh)]
            elif m == 1:
                data += [1 - v.x / wc, (v.y + hh) / (2 * hh)]
            else:
                data += [(v.x + v.y) / 0.6, v.z / 0.6]
    uv.data.foreach_set('uv', data)
    return me


def bevel(ob, width=0.010, segs=3):
    m = ob.modifiers.new('Bevel', 'BEVEL')
    m.width = width
    m.segments = segs
    m.limit_method = 'ANGLE'
    m.harden_normals = False
    ob.data.polygons.foreach_set('use_smooth', [False] * len(ob.data.polygons))
    return m


# ---- spine -------------------------------------------------------------------------------
SPINE_N = 40
SPINE_LEATHER = 0.008


def spine_coords(theta):
    c = G.spine_curve(theta, SPINE_N)                     # outer surface, from back board to front board
    tang = np.gradient(c, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    inward = np.c_[tang[:, 1], -tang[:, 0]]                 # points into the book
    ci = c + inward * SPINE_LEATHER
    out = []
    for yy in (-G.HC / 2, G.HC / 2):
        out += [(x, yy, z) for x, z in c]
    for yy in (-G.HC / 2, G.HC / 2):
        out += [(x, yy, z) for x, z in ci]
    return np.array(out)


def spine_mesh():
    n = SPINE_N
    o0, o1, i0, i1 = 0, n, 2 * n, 3 * n
    faces, mats, uvs = [], [], []
    for k in range(n - 1):
        faces.append((o0 + k, o0 + k + 1, o1 + k + 1, o1 + k)); mats.append(0)
        uvs.append([(k / (n - 1), 0), ((k + 1) / (n - 1), 0), ((k + 1) / (n - 1), 1), (k / (n - 1), 1)])
        faces.append((i1 + k, i1 + k + 1, i0 + k + 1, i0 + k)); mats.append(1)
        uvs.append([(0, 0)] * 4)
        faces.append((i0 + k, i0 + k + 1, o0 + k + 1, o0 + k)); mats.append(1)    # bottom end
        uvs.append([(0, 0)] * 4)
        faces.append((o1 + k, o1 + k + 1, i1 + k + 1, i1 + k)); mats.append(1)    # top end
        uvs.append([(0, 0)] * 4)
    me = bpy.data.meshes.new('Spine')
    me.from_pydata([(0, 0, 0)] * (4 * n), [], faces)
    me.polygons.foreach_set('material_index', mats)
    me.polygons.foreach_set('use_smooth', [True] * len(faces))
    uv = me.uv_layers.new(name='UVMap')
    uv.data.foreach_set('uv', [c for f in uvs for v in f for c in v])
    return me


def core_coords(theta):
    """Back of the text block, filling the space inside the rounded spine."""
    c = G.spine_curve(theta, SPINE_N)
    tang = np.gradient(c, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    ci = c + np.c_[tang[:, 1], -tang[:, 0]] * (SPINE_LEATHER + 0.001)
    # the other side of the filler follows the seams (a column when closed, the hump when open)
    seams = np.array([G.core_seam(jj) for jj in range(G.N_SHEETS)]) - np.array([0.0, 0.0012])
    tt = np.linspace(0, 1, SPINE_N)
    ts = np.linspace(0, 1, len(seams))
    line = np.c_[np.interp(tt, ts, seams[:, 0]), np.interp(tt, ts, seams[:, 1])]
    out = []
    for yy in (-G.H / 2 - 0.004, G.H / 2 + 0.004):
        out += [(x, yy, z) for x, z in ci] + [(x, yy, z) for x, z in line]
    return np.array(out)


def core_mesh():
    n = SPINE_N
    faces = []
    for e, (a0, b0) in enumerate([(0, n), (2 * n, 3 * n)]):
        for k in range(n - 1):
            f = (a0 + k, a0 + k + 1, b0 + k + 1, b0 + k)
            faces.append(f if e else f[::-1])
    for k in range(n - 1):
        faces.append((k, 2 * n + k, 2 * n + k + 1, k + 1))
    me = bpy.data.meshes.new('SpineCore')
    me.from_pydata([(0, 0, 0)] * (4 * n), [], faces)
    return me




# ---- pages -------------------------------------------------------------------------------
def page_material(name, paper, content, roughness=0.72):
    """Paper texture with the page's own image on top (its alpha decides where the paper shows).
    A full-bleed page image (parchment included) simply replaces the paper."""
    mat = bpy.data.materials.new(name)
    nt, bsdf, out = principled(mat)
    base = nt.nodes.new('ShaderNodeTexImage')
    base.image = image(paper)
    base.interpolation = 'Cubic'
    base.extension = 'EXTEND'
    col = base.outputs['Color']
    if content:
        tx = nt.nodes.new('ShaderNodeTexImage')
        tx.image = image(content)
        tx.interpolation = 'Cubic'
        tx.extension = 'EXTEND'
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        nt.links.new(tx.outputs['Alpha'], mix.inputs['Factor'])
        nt.links.new(base.outputs['Color'], mix.inputs['A'])
        nt.links.new(tx.outputs['Color'], mix.inputs['B'])
        col = mix.outputs['Result']
    nt.links.new(col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Specular IOR Level'].default_value = 0.3
    tr = nt.nodes.new('ShaderNodeBsdfTranslucent')
    nt.links.new(col, tr.inputs['Color'])
    mx = nt.nodes.new('ShaderNodeMixShader')
    mx.inputs['Fac'].default_value = 0.03
    nt.links.new(bsdf.outputs['BSDF'], mx.inputs[1])
    nt.links.new(tr.outputs['BSDF'], mx.inputs[2])
    nt.links.new(mx.outputs['Shader'], out.inputs['Surface'])
    return mat


def surface(name, path, fallback_rgb, **kw):
    if path and os.path.exists(path):
        return image_material(name, path, **kw)
    return color_material(name, tuple(fallback_rgb), 0.6)




def build(job):
    book = job['book']
    sheets = int(job.get('page_count') or book.get('page_count') or 10)
    G.configure(sheets, float(book.get('page_aspect', 1.4318)), **G.book_dims(book), page_shape=job.get('page_shape', 'flat'),
                turn_style=job.get('turn_style', 'natural'))
    images = list(job.get('images') or [])
    leather_rgb = book.get('leather_color', (0.12, 0.05, 0.02))

    m_front = surface('FrontExterior', book.get('front_exterior_image'), leather_rgb, roughness=0.62, bump=0.35, spec=0.3)
    m_back = surface('BackExterior', book.get('back_exterior_image'), leather_rgb, roughness=0.62, bump=0.35, spec=0.3)
    m_pd_f = surface('PastedownFront', book.get('front_interior_image'), leather_rgb, roughness=0.62, bump=0.3, spec=0.3)
    m_pd_b = surface('PastedownBack', book.get('back_interior_image'), leather_rgb, roughness=0.62, bump=0.3, spec=0.3)
    # the boards' edges (and the inside of the spine) in the cover's own colour when asked ('match')
    edge_img = book.get('edge_image') or book.get('leather_image')
    m_leather = surface('LeatherPlain', edge_img, leather_rgb, roughness=0.6, bump=0.3, spec=0.3)
    m_spine = surface('Spine', book.get('spine_exterior_image'), leather_rgb, roughness=0.55, bump=0.4, spec=0.35)
    m_spine_in = surface('SpineInside', edge_img, leather_rgb, roughness=0.75, bump=0.2, spec=0.2)
    if edge_img:
        _darken(m_spine_in, 0.45)
    m_edge = page_edge_material()
    m_core = color_material('TextBlockBack', (0.16, 0.09, 0.05), 0.75, noise=0.3)
    paper = book.get('paper_image')
    paper_odd = book.get('paper_odd_image') or paper
    paper_even = book.get('paper_even_image') or paper

    root = bpy.data.objects.new('Book', None)
    bpy.context.scene.collection.objects.link(root)
    tf = job.get('transform') or {}
    root.location = tuple(float(v) for v in tf.get('pos', (0.0, 0.0, 0.0)))
    root.rotation_euler = tuple(math.radians(float(v)) for v in tf.get('rot', (0.0, 0.0, 0.0)))
    root.scale = tuple(float(v) for v in tf.get('scale', (1.0, 1.0, 1.0)))

    corner = float(book.get('board_corner') or 0.035 / 1.08) * G.WC     # as round as the cover art's corners
    bb = new_object('BackBoard', board_mesh('BackBoard', rad=corner), root)
    bb.location = (G.XB, 0, 0)
    for m in (m_pd_b, m_back, m_leather):
        bb.data.materials.append(m)
    bevel(bb)
    pivot = bpy.data.objects.new('FrontHinge', None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.parent = root
    pivot.location = (G.J[0], 0, G.J[1])
    pivot.rotation_mode = 'XYZ'
    fb = new_object('FrontBoard', board_mesh('FrontBoard', rad=corner), pivot)
    for m in (m_front, m_pd_f, m_leather):
        fb.data.materials.append(m)
    bevel(fb)

    sp = new_object('Spine', spine_mesh(), root)
    sp.data.materials.append(m_spine)
    sp.data.materials.append(m_spine_in)
    core = new_object('SpineCore', core_mesh(), root)
    core.data.materials.append(m_core)

    # joint ribbon: covers the groove between the open cover and the first page
    jr_me = bpy.data.meshes.new('Joint')
    zb = G.core_seam(G.N_SHEETS - 1)
    ts = np.linspace(0, 1, 8)
    jo = G.J_OPEN    # from the open cover's hinge up to the top of the text block, in the gutter
    prof = [(jo[0] + (zb[0] + 0.002 - jo[0]) * t, jo[1] - 0.002 + (zb[1] - jo[1]) * t - 0.006 * math.sin(math.pi * t)) for t in ts]
    jr_me.from_pydata([(x, yy, z) for yy in (-G.H / 2 - 0.02, G.H / 2 + 0.02) for x, z in prof], [],
                      [(k, k + 1, 9 + k, 8 + k) for k in range(7)])
    jr_me.uv_layers.new(name='UVMap').data.foreach_set(
        'uv', [c for k in range(7) for c in (k / 7, 0, (k + 1) / 7, 0, (k + 1) / 7, 1, k / 7, 1)])
    jr = new_object('Joint', jr_me, root)
    jr.data.materials.append(surface('JointStrip', book.get('joint_image') or book.get('leather_image'),
                                     leather_rgb, roughness=0.55, bump=0.3))

    # sheets: sheet k (0 = first sheet inside the cover) carries images[2k] (front) and images[2k+1] (back)
    get = lambda i: images[i] if 0 <= i < len(images) else None  # noqa: E731
    obs = []
    for k in range(G.N_SHEETS):
        me = sheet_mesh(f'Sheet{k + 1:02d}', G.NY, G.NX)
        ob = new_object(f'Sheet{k + 1:02d}', me, root)
        for m in (page_material(f'Page{2 * k + 1:03d}', paper_odd, get(2 * k)),
                  page_material(f'Page{2 * k + 2:03d}', paper_even, get(2 * k + 1)), m_edge):
            ob.data.materials.append(m)
        obs.append(ob)
    strap = build_strap(root, m_leather) if book.get('strap') else None
    return root, pivot, sp, core, obs, strap


def _box(name, x0, x1, w, z0, z1, tip=0.0):
    """A leather strip: x from x0 to x1, y across w, z from z0 to z1; the x0 end rounded when
    tip > 0 (a half circle of radius tip)."""
    if tip:
        n = 8
        outline = [(x1, -w / 2)]
        cx = x0 + tip
        for k in range(n + 1):
            a = -math.pi / 2 - k * math.pi / n
            outline.append((cx + tip * math.cos(a), tip * math.sin(a)))
        outline.append((x1, w / 2))
    else:
        outline = [(x1, -w / 2), (x0, -w / 2), (x0, w / 2), (x1, w / 2)]
    m = len(outline)
    verts = [(x, y, z0) for x, y in outline] + [(x, y, z1) for x, y in outline]
    faces = [tuple(range(m, 2 * m)), tuple(range(m - 1, -1, -1))]
    faces += [(k, (k + 1) % m, m + (k + 1) % m, m + k) for k in range(m)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    return me


def build_strap(root, material):
    """The journal's leather strap: up the fore-edge from the back cover, and a tongue over the
    front cover. Two hinges (at the back cover, at the fore-edge's top) undo it."""
    ax, h, L = G.strap_dims()
    w, t = G.STRAP_W, G.STRAP_T
    e1 = bpy.data.objects.new('StrapHinge', None)
    bpy.context.scene.collection.objects.link(e1)
    e1.parent = root
    e1.location = (ax, 0.0, 0.0)
    e1.rotation_mode = 'XYZ'
    up = new_object('StrapEdge', _box('StrapEdge', -t / 2, t / 2, w, 0.0, h), e1)
    e2 = bpy.data.objects.new('StrapFold', None)
    bpy.context.scene.collection.objects.link(e2)
    e2.parent = e1
    e2.location = (0.0, 0.0, h)
    e2.rotation_mode = 'XYZ'
    tongue = new_object('StrapTongue', _box('StrapTongue', -L, t / 2, w, -t, 0.0, tip=w / 2), e2)
    for ob in (up, tongue):
        ob.data.materials.append(material)
        bevel(ob, width=0.003, segs=2)
    return e1, e2


def strap_u_at(f, c_start, fps, starts_closed):
    """How far the strap is undone at frame f (0 fastened .. 1 open): it is undone in the second
    before the cover starts to open (sooner if the video starts closer to the opening)."""
    if not starts_closed:
        return 1.0
    end = c_start - round(0.45 * fps)
    span = max(2, min(round(1.0 * fps), end))
    begin = end - span
    return min(1.0, max(0.0, (f - begin) / span))


def sheet_coords(k, t, curve=1.0):
    return G.solid_from_grid(G.sheet_state(k, t, curve))


def setup_lights_world():
    def area(name, loc, power, size, color, target=(0.0, 0.0, 0.2)):
        light = bpy.data.lights.new(name, 'AREA')
        light.energy, light.size, light.color = power, size, color
        o = bpy.data.objects.new(name, light)
        bpy.context.scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = _look(np.array(target) - np.array(loc))
    area('Key', (-2.3, -2.4, 3.8), 520, 1.6, (1.0, 0.95, 0.88))
    area('Fill', (3.0, -2.2, 2.2), 140, 3.0, (0.85, 0.9, 1.0))
    area('Rim', (1.2, 3.2, 2.6), 260, 2.0, (1.0, 0.9, 0.78))
    world = bpy.data.worlds.new('World')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.05, 0.045, 0.04, 1)
    bpy.context.scene.world = world


def add_shadow_catcher(root):
    """Cycles only: an invisible surface just under the back board that only catches the
    book's shadow. It is attached to the book, so a rotated or moved book never sinks into it.
    (EEVEE cannot make a surface shadow-only - it would render as a white floor - so the fast
    modes have no table, like the classic engine.)"""
    if bpy.context.scene.render.engine != 'CYCLES':
        return
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0))   # big: an arm's shadow reaches far
    table = bpy.context.active_object
    table.name = 'ShadowCatcher'
    table.is_shadow_catcher = True
    table.parent = root
    table.location = (0.5, 0.0, -0.0008)


def place_camera(cam, job, frac):
    """The app's camera settings (preset, zoom, shift, slow move), framed like the live preview."""
    pos, r, u, f, lens = G.camera(job['cam'], frac, job['width'] / job['height'], G.real_size(job.get('book')))
    from mathutils import Matrix
    cam.matrix_world = Matrix([[r[i], u[i], -f[i], pos[i]] for i in range(3)] + [[0.0, 0.0, 0.0, 1.0]])
    cam.data.lens = float(lens)


def _look(d):
    from mathutils import Vector
    return Vector(tuple(float(x) for x in d)).to_track_quat('-Z', 'Y').to_euler()


def tune_cycles(scene):
    """Photoreal speed: keep the scene loaded between frames (only the moving pages are
    updated), denoise on the graphics card, and stop sampling early where a pixel is clean."""
    c = scene.cycles
    c.max_bounces, c.diffuse_bounces, c.glossy_bounces = 4, 2, 1
    c.transmission_bounces, c.volume_bounces, c.transparent_max_bounces = 1, 0, 4
    c.caustics_reflective = c.caustics_refractive = False
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.03
    c.samples = min(int(c.samples), 64)
    scene.render.use_persistent_data = True       # no full scene rebuild per frame
    gpu = c.device == 'GPU'
    try:
        kind = bpy.context.preferences.addons['cycles'].preferences.compute_device_type
    except Exception:
        kind = None
    for attr, val in (('denoiser', 'OPTIX' if gpu and kind == 'OPTIX' else 'OPENIMAGEDENOISE'),
                      ('denoising_use_gpu', gpu), ('denoising_prefilter', 'FAST')):
        try:
            setattr(c, attr, val)
        except (AttributeError, TypeError):
            pass
    log(f'INFO Cycles tuned: {c.samples} samples (adaptive), persistent data, denoiser {c.denoiser}'
        f'{" on GPU" if gpu else ""}')


def make_hands(job, root, sc, n_sheets, strap_u, held_up):
    """The hands and their poses for every frame: (hand, plan, left hand, left plan), each None
    when not shown. Shared by the render and the live view's hand bake (hand_bake.py), so the
    live view moves exactly as the video."""
    if not job.get('hand'):
        return None, None, None, None
    import hand_scene

    def state_at(f):
        pose = sc.evaluate(f)
        theta = G.cover_angle(float(pose['cover_progress']))
        G.set_opening(theta)
        prog = pose['sheet_progress']
        ts = [float(prog[k]) if k < len(prog) else 0.0 for k in range(n_sheets)]
        G.set_turned(ts)
        return ts, G.curve_weights(ts), theta
    cm = (job['book'].get('page_size_cm') or [G.REF_PAGE_CM[0]])[0]
    # a smaller hand on this book looks just like a real-size hand on a bigger book
    cm = float(cm) / min(max(float(job.get('hand_size') or 1.0), 0.4), 2.0)
    hand = hand_scene.Hand(root, float(cm), G.H / 2)
    hand.set_look(job.get('hand_skin'), job.get('hand_sleeve'))
    hand_plan = hand_scene.plan(hand, sc.frames, job['fps'], state_at, strap_u, held_up)
    left = left_plan = None
    if job.get('hand_left', True):                 # the left hand holds the book
        style = 'under' if held_up else 'on'
        left = hand_scene.Hand(root, float(cm), G.H / 2, mirror=True,
                               shoulder_cm=hand_scene.LEFT_SHOULDER_UNDER_CM if held_up else None,
                               elbow_floor=not held_up)
        left.set_look(job.get('hand_skin'), job.get('hand_sleeve'))
        left_plan = hand_scene.plan_left(left, sc.frames, job['fps'], state_at, hand_plan, style)
    log('INFO hand turns the pages')
    return hand, hand_plan, left, left_plan


def job_scene(job):
    """The animation timeline for a job (as the render uses it) and its strap timing."""
    turns, _, _, _ = layout_pages(len(job.get('images') or []))
    scheduled = job.get('turns')
    sc = scene.Scene(turns if scheduled is None else int(scheduled),
                     job['book']['page_aspect'], job.get('open_at', 0.0), job['fps'],
                     job['start_hold'], job['turn_seconds'], job['pause'], job['end_hold'],
                     job.get('open_seconds', 0.0), job.get('slide', True),
                     page_count=G.N_SHEETS, smoothness=job.get('smoothness', 1.0),
                     recorded_clips=job.get('recorded_clips'), clip_list=job.get('clip_list'))
    return sc


def main():
    job_path = sys.argv[sys.argv.index('--') + 1]
    with open(job_path, encoding='utf-8') as fh:
        job = json.load(fh)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_render(job)
    sc_b = bpy.context.scene
    sc_b.view_settings.view_transform = 'Standard'
    sc_b.view_settings.exposure = -1.25
    if sc_b.render.engine == 'CYCLES':
        tune_cycles(sc_b)
    root, pivot, sp, core, obs, strap = build(job)
    setup_lights_world()
    held_up = bool(job.get('hand')) and job.get('hand_left', True) and job.get('hand_left_style') == 'under'
    if not held_up:                    # a book held up in the hand has no table under it
        add_shadow_catcher(root)
    cam_data = bpy.data.cameras.new('Camera')
    cam_data.sensor_width = 36.0
    cam_data.sensor_fit = 'HORIZONTAL'
    cam_data.clip_start, cam_data.clip_end = 0.05, 200
    cam = bpy.data.objects.new('Camera', cam_data)
    sc_b.collection.objects.link(cam)
    sc_b.camera = cam

    sc = job_scene(job)
    turns = layout_pages(len(job.get('images') or []))[0]   # (as written to sequence.json)
    starts_closed = sc.evaluate(0)['cover_progress'] < 1.0 - 1e-6
    c_start = next((f for f in range(sc.frames) if sc.evaluate(f)['cover_progress'] > 1e-6), 0)
    strap_u = [strap_u_at(f, c_start, job['fps'], starts_closed) for f in range(sc.frames)] if strap else None
    hand, hand_plan, left, left_plan = make_hands(job, root, sc, len(obs), strap_u, held_up)
    frames = job.get('frames') or list(range(sc.frames))
    total_frames = len(frames)
    offset = 0
    chunk = job.get('chunk')           # [k, n]: this Blender renders part k of n (side by side)
    if chunk:
        k, n = int(chunk[0]), int(chunk[1])
        a, b = len(frames) * k // n, len(frames) * (k + 1) // n
        frames, offset = frames[a:b], a
    out = job['out_dir']
    os.makedirs(out, exist_ok=True)
    last = [None] * len(obs)
    last_w = None
    last_key, last_path = None, None
    base_loc = tuple(root.location)
    last_theta = None
    last_core = None
    started = time.time()
    log(f'TOTAL {len(frames)}')
    for i, f in enumerate(frames):
        pose = sc.evaluate(f)
        theta = G.cover_angle(float(pose['cover_progress']))
        w_open = G.set_opening(theta)            # pages relax into their curve as the cover opens
        w_open = (round(w_open, 7), round(G.OPEN_B, 7))   # ...and the spine rolls open under them
        if w_open != last_w:
            last = [None] * len(obs)
            last_w = w_open
        root.location = (base_loc[0] + float(pose.get('cover_slide', 0.0)), base_loc[1], base_loc[2])
        pivot.rotation_euler = (0.0, -theta, 0.0)
        pv = G.cover_pivot(theta)
        pivot.location = (float(pv[0]), 0.0, float(pv[1]))
        prog = pose['sheet_progress']
        ts = [float(prog[k]) if k < len(prog) else 0.0 for k in range(len(obs))]
        turned = round(G.set_turned(ts), 6)   # the spine's crest sits between turned and unturned pages
        if theta != last_theta:
            set_coords(sp.data, spine_coords(theta))
            last_theta = theta
        if (theta, turned) != last_core:
            set_coords(core.data, core_coords(theta))
            last_core = (theta, turned)
        place_camera(cam, job, pose['camera_frac'])
        cw = G.curve_weights(ts)          # only the visible spread is curved; pages under it are flat
        for k, ob in enumerate(obs):
            state = (ts[k], round(cw[k], 6), turned)
            if state != last[k]:
                set_coords(ob.data, sheet_coords(k, ts[k], cw[k]))
                last[k] = state
        strap_key = None
        if strap is not None:
            su = strap_u[min(f, len(strap_u) - 1)]
            a1, a2 = G.strap_state(su)
            strap[0].rotation_euler = (0.0, a1, 0.0)
            strap[1].rotation_euler = (0.0, a2, 0.0)
            strap_key = round(su, 5)
        hand_key = None
        if hand_plan is not None:
            hp = hand_plan[min(f, len(hand_plan) - 1)]
            hand.apply(hp)
            hand_key = tuple(round(float(x), 5) for part in hp[:3] for x in part) + tuple(round(float(x), 4) for x in hp[3:])
        if left_plan is not None:
            lp = left_plan[min(f, len(left_plan) - 1)]
            left.apply(lp)
            hand_key = (hand_key, tuple(round(float(x), 5) for part in lp[:3] for x in part))
        path = os.path.join(out, f'frame_{offset + i:06d}.png')
        cam_key = None if job['cam'].get('move', 'none') == 'none' else round(float(pose['camera_frac']), 6)
        key = (round(theta, 7), w_open, tuple(round(float(x), 7) for x in prog), cam_key,
               round(float(pose.get('cover_slide', 0.0)), 7), hand_key, strap_key)
        if key == last_key and last_path:
            shutil.copyfile(last_path, path)          # nothing moved: same picture, no render
        else:
            sc_b.frame_current = f
            sc_b.render.filepath = path
            bpy.ops.render.render(write_still=True)
            last_key, last_path = key, path
        log(f'PROGRESS {i + 1} {len(frames)}')
    if chunk and int(chunk[0]) != 0:
        log('DONE')
        return
    with open(os.path.join(out, 'sequence.json'), 'w', encoding='utf-8') as fh:
        json.dump(dict(width=job['width'], height=job['height'], fps=job['fps'], frames=total_frames,
                       turns=turns, seconds=round(total_frames / job['fps'], 3), alpha=True,
                       render_seconds=round(time.time() - started, 1)), fh, indent=2)
    log('DONE')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        log(f'ERROR {exc}')
        sys.stdout.flush()
        os._exit(1)
