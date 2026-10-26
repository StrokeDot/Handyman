"""Builds a book from a template inside Blender and renders transparent PNG frames.

The app runs this for you in the background:
    blender -b --factory-startup -P book_scene.py -- job.json
You never need to open Blender.
"""
import json
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import book_model as bm  # noqa: E402
import scene  # noqa: E402
from page_curl import ease, sheet_vertices, grid_faces, grid_uvs, layout_pages  # noqa: E402

PAGE_W = bm.PAGE_W
PAGE_H = 1.4              # replaced from the template's page_aspect
COVER_MARGIN = bm.COVER_MARGIN
COVER_T = bm.COVER_T
LAYOUT = bm.Layout()      # replaced in build_book
GRID_X, GRID_Y = 48, 28
BOOK_POS = (0.0, 0.0, 0.0)   # the book's whole-object position (the cover slide is added on top)


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- node helpers

def sock(sockets, name, kind=None):
    for s in sockets:
        if s.name == name and getattr(s, 'enabled', True) and (kind is None or s.type == kind):
            return s
    raise KeyError(name)


def set_input(node, name, value):
    try:
        sock(node.inputs, name).default_value = value
    except KeyError:
        pass  # socket renamed in this Blender version; keep the default


def link(nt, src, node, name):
    try:
        nt.links.new(src, sock(node.inputs, name))
    except KeyError:
        pass


def new_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat, nt, bsdf, out


def use_alpha_cutout(mat):
    """Let transparent parts of an image (around an emblem) disappear, shadows included."""
    for attr, value in (('surface_render_method', 'DITHERED'), ('blend_method', 'CLIP'),
                        ('shadow_method', 'CLIP')):
        try:
            setattr(mat, attr, value)
        except (AttributeError, TypeError):
            pass


def mix_rgb(nt, blend, fac, a, b):
    """Colour mix; fac/a/b may be sockets or constants. Returns the result socket."""
    m = nt.nodes.new('ShaderNodeMix')
    m.data_type = 'RGBA'
    m.blend_type = blend
    for name, val in (('Factor', fac), ('A', a), ('B', b)):
        kind = 'VALUE' if name == 'Factor' else 'RGBA'
        s = sock(m.inputs, name, kind)
        if isinstance(val, bpy.types.NodeSocket):
            nt.links.new(val, s)
        else:
            s.default_value = val
    return sock(m.outputs, 'Result', 'RGBA')


def math_node(nt, op, a, b=None):
    n = nt.nodes.new('ShaderNodeMath')
    n.operation = op
    for i, val in enumerate((a, b)):
        if val is None:
            continue
        if isinstance(val, bpy.types.NodeSocket):
            nt.links.new(val, n.inputs[i])
        else:
            n.inputs[i].default_value = val
    return n.outputs[0]


def ramp(nt, src, stops):
    r = nt.nodes.new('ShaderNodeValToRGB')
    nt.links.new(src, r.inputs['Fac'])
    els = r.color_ramp.elements
    els[0].position, els[0].color = stops[0]
    els[1].position, els[1].color = stops[-1]
    for pos, col in stops[1:-1]:
        e = els.new(pos)
        e.color = col
    return r.outputs['Color']


def bump(nt, height, strength, distance=0.02):
    b = nt.nodes.new('ShaderNodeBump')
    set_input(b, 'Strength', strength)
    set_input(b, 'Distance', distance)
    nt.links.new(height, b.inputs['Height'])
    return b.outputs['Normal']


def rgba(c, k=1.0):
    return (min(1.0, c[0] * k), min(1.0, c[1] * k), min(1.0, c[2] * k), 1.0)


def load_image(path):
    try:
        img = bpy.data.images.load(path, check_existing=True)
    except RuntimeError:
        log(f'WARNING could not open image {path}')
        return None
    iw, ih = img.size
    if not iw or not ih:
        log(f'WARNING could not read image {path}')
        return None
    return img


# ------------------------------------------------------------------ materials

def leather_material(color, name='Leather', k=1.0, image=None):
    """Leather: the bundled photo texture when given, else the procedural pebbled grain."""
    mat, nt, bsdf, _ = new_material(name)
    if image:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = bpy.data.images.load(str(image), check_existing=True)
        tex.interpolation = 'Cubic'
        gen = nt.nodes.new('ShaderNodeTexCoord').outputs['Generated']
        nt.links.new(gen, tex.inputs['Vector'])
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        lum = nt.nodes.new('ShaderNodeRGBToBW')
        nt.links.new(tex.outputs['Color'], lum.inputs[0])
        nt.links.new(bump(nt, lum.outputs[0], 0.18, 0.003), bsdf.inputs['Normal'])
        set_input(bsdf, 'Roughness', 0.62)
        set_input(bsdf, 'Coat Weight', 0.1)
        set_input(bsdf, 'Coat Roughness', 0.4)
        return mat
    coord = nt.nodes.new('ShaderNodeTexCoord').outputs['Object']
    tone = nt.nodes.new('ShaderNodeTexNoise')
    set_input(tone, 'Scale', 9.0)
    set_input(tone, 'Detail', 6.0)
    set_input(tone, 'Roughness', 0.45)
    nt.links.new(coord, tone.inputs['Vector'])
    base = ramp(nt, tone.outputs['Fac'], [(0.25, rgba(color, 0.82 * k)), (0.55, rgba(color, k)),
                                          (0.85, rgba(color, 1.12 * k))])

    # Pebbled grain: small cells, darker in the creases between them.
    grain = nt.nodes.new('ShaderNodeTexVoronoi')
    set_input(grain, 'Scale', 320.0)
    set_input(grain, 'Randomness', 0.9)
    nt.links.new(coord, grain.inputs['Vector'])
    cell = sock(grain.outputs, 'Distance')
    crease = nt.nodes.new('ShaderNodeMapRange')
    nt.links.new(cell, crease.inputs['Value'])
    set_input(crease, 'From Min', 0.0)
    set_input(crease, 'From Max', 0.35)
    set_input(crease, 'To Min', 0.0)
    set_input(crease, 'To Max', 1.0)
    base = mix_rgb(nt, 'MULTIPLY', math_node(nt, 'MULTIPLY', crease.outputs['Result'], 0.18), base, (0.6, 0.6, 0.6, 1))
    nt.links.new(base, bsdf.inputs['Base Color'])

    pores = nt.nodes.new('ShaderNodeTexNoise')
    set_input(pores, 'Scale', 900.0)
    nt.links.new(coord, pores.inputs['Vector'])
    height = math_node(nt, 'ADD', math_node(nt, 'MULTIPLY', cell, -1.0), math_node(nt, 'MULTIPLY', pores.outputs['Fac'], 0.15))
    nt.links.new(bump(nt, height, 0.22, 0.004), bsdf.inputs['Normal'])

    rough = nt.nodes.new('ShaderNodeMapRange')
    nt.links.new(tone.outputs['Fac'], rough.inputs['Value'])
    set_input(rough, 'To Min', 0.45)
    set_input(rough, 'To Max', 0.68)
    nt.links.new(rough.outputs['Result'], bsdf.inputs['Roughness'])
    set_input(bsdf, 'Coat Weight', 0.12)        # a faint waxed sheen
    set_input(bsdf, 'Coat Roughness', 0.35)
    return mat


def plain_material(name, color, roughness=0.6, metallic=0.0):
    mat, nt, bsdf, _ = new_material(name)
    bsdf.inputs['Base Color'].default_value = rgba(color)
    set_input(bsdf, 'Roughness', roughness)
    set_input(bsdf, 'Metallic', metallic)
    return mat


def paper_tone(book, shade):
    fresh = np.array(book['paper_color'])
    old = fresh * np.array([0.78, 0.68, 0.52])
    c = fresh + (old - fresh) * book['paper_age']
    c = c * (1.0 - 0.35 * shade)
    return (float(c[0]), float(c[1]), float(c[2]), 1.0)


def page_edge_material(book):
    """Stacked paper seen from the side: hundreds of fine sheet lines, darker towards the edges."""
    mat, nt, bsdf, _ = new_material('PageEdges')
    coord = nt.nodes.new('ShaderNodeTexCoord').outputs['Object']
    wave = nt.nodes.new('ShaderNodeTexWave')
    wave.wave_type = 'BANDS'
    wave.bands_direction = 'Z'
    set_input(wave, 'Scale', 900.0)
    set_input(wave, 'Distortion', 1.5)
    set_input(wave, 'Detail', 3.0)
    nt.links.new(coord, wave.inputs['Vector'])
    dirt = nt.nodes.new('ShaderNodeTexNoise')
    set_input(dirt, 'Scale', 14.0)
    nt.links.new(coord, dirt.inputs['Vector'])
    light = paper_tone(book, 0.0)
    col = ramp(nt, wave.outputs['Fac'], [(0.0, rgba(light, 0.62)), (0.5, rgba(light, 0.92)), (1.0, light)])
    col = mix_rgb(nt, 'MULTIPLY', math_node(nt, 'MULTIPLY', dirt.outputs['Fac'], 0.5 * book['burn'] + 0.1),
                  col, (0.45, 0.30, 0.18, 1))
    nt.links.new(col, bsdf.inputs['Base Color'])
    nt.links.new(bump(nt, wave.outputs['Fac'], 0.3, 0.002), bsdf.inputs['Normal'])
    set_input(bsdf, 'Roughness', 0.92)
    return mat


def image_layer(nt, uv, path, back, margin):
    """Returns (colour, alpha) sockets of an image fitted inside the page, or None."""
    img = load_image(path) if path else None
    if img is None:
        return None
    iw, ih = img.size
    mw = margin * PAGE_W
    k = min((PAGE_W - 2 * mw) / iw, (PAGE_H - 2 * mw) / ih)
    bw, bh = iw * k / PAGE_W, ih * k / PAGE_H
    u0, v0 = (1 - bw) / 2, (1 - bh) / 2

    vec = uv
    if back:  # the back of a sheet is seen mirrored across the spine
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(uv, sep.inputs[0])
        comb = nt.nodes.new('ShaderNodeCombineXYZ')
        nt.links.new(math_node(nt, 'SUBTRACT', 1.0, sep.outputs['X']), comb.inputs['X'])
        nt.links.new(sep.outputs['Y'], comb.inputs['Y'])
        vec = comb.outputs[0]
    mp = nt.nodes.new('ShaderNodeMapping')
    nt.links.new(vec, mp.inputs['Vector'])
    mp.inputs['Scale'].default_value = (1 / bw, 1 / bh, 1)
    mp.inputs['Location'].default_value = (-u0 / bw, -v0 / bh, 0)
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    tex.extension = 'CLIP'
    tex.interpolation = 'Cubic'
    nt.links.new(mp.outputs['Vector'], tex.inputs['Vector'])
    return tex.outputs['Color'], tex.outputs['Alpha']


def sheet_material(name, front, back, job):
    """Parchment with an image on each side (either may be None)."""
    book = job['book']
    mat, nt, bsdf, out = new_material(name)
    uv = nt.nodes.new('ShaderNodeTexCoord').outputs['UV']
    gen = nt.nodes.new('ShaderNodeTexCoord').outputs['Generated']

    # Blotchy aged paper with darker, burnt-looking edges.
    blotch = nt.nodes.new('ShaderNodeTexNoise')
    set_input(blotch, 'Scale', 5.0)
    set_input(blotch, 'Detail', 6.0)
    nt.links.new(uv, blotch.inputs['Vector'])
    paper = ramp(nt, blotch.outputs['Fac'], [(0.35, paper_tone(book, 0.4 * book['paper_age'])),
                                             (0.65, paper_tone(book, 0.0))])
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(uv, sep.inputs[0])
    u, v = sep.outputs['X'], sep.outputs['Y']
    edge = math_node(nt, 'MINIMUM',
                     math_node(nt, 'MINIMUM', u, math_node(nt, 'SUBTRACT', 1.0, u)),
                     math_node(nt, 'MINIMUM', v, math_node(nt, 'SUBTRACT', 1.0, v)))
    # Wobble the edge so the burn is irregular, not a clean frame.
    wob = nt.nodes.new('ShaderNodeTexNoise')
    set_input(wob, 'Scale', 14.0)
    nt.links.new(uv, wob.inputs['Vector'])
    edge = math_node(nt, 'ADD', edge, math_node(nt, 'MULTIPLY', wob.outputs['Fac'], 0.03))
    vign = nt.nodes.new('ShaderNodeMapRange')
    nt.links.new(edge, vign.inputs['Value'])
    set_input(vign, 'From Min', 0.012)
    set_input(vign, 'From Max', 0.03 + 0.07 * book['burn'])
    set_input(vign, 'To Min', 0.9 * book['burn'])
    set_input(vign, 'To Max', 0.0)
    paper = mix_rgb(nt, 'MULTIPLY', vign.outputs['Result'], paper, (0.30, 0.16, 0.07, 1))

    if book.get('paper_image'):
        paper_tex = nt.nodes.new('ShaderNodeTexImage')
        paper_tex.image = bpy.data.images.load(str(book['paper_image']), check_existing=True)
        paper_tex.interpolation = 'Cubic'
        nt.links.new(uv, paper_tex.inputs['Vector'])
        paper = paper_tex.outputs['Color']

    blend = 'MULTIPLY' if job['blend'] == 'ink' else 'MIX'
    sides = []
    for side_path, is_back in ((front, False), (back, True)):
        layer = image_layer(nt, uv, side_path, is_back, job['margin'])
        if layer:
            col, alpha = layer
            fac = math_node(nt, 'MULTIPLY', alpha, job['image_strength'])
            sides.append(mix_rgb(nt, blend, fac, paper, col))
        else:
            sides.append(paper)
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    color = mix_rgb(nt, 'MIX', geo.outputs['Backfacing'], sides[0], sides[1])
    nt.links.new(color, bsdf.inputs['Base Color'])
    set_input(bsdf, 'Roughness', 0.88)

    fibre = nt.nodes.new('ShaderNodeTexNoise')
    set_input(fibre, 'Scale', 220.0)
    nt.links.new(gen, fibre.inputs['Vector'])
    nt.links.new(bump(nt, fibre.outputs['Fac'], 0.05, 0.005), bsdf.inputs['Normal'])

    # A little light shines through a lifted page.
    trans = nt.nodes.new('ShaderNodeBsdfTranslucent')
    nt.links.new(color, trans.inputs['Color'])
    mix = nt.nodes.new('ShaderNodeMixShader')
    mix.inputs['Fac'].default_value = 0.12
    nt.links.new(bsdf.outputs['BSDF'], mix.inputs[1])
    nt.links.new(trans.outputs['BSDF'], mix.inputs[2])
    nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    return mat


def emblem_material(img, style, leather):
    """Medallion: the picture as it is, with a little relief. Deboss: pressed, darkened leather."""
    mat, nt, bsdf, _ = new_material('Emblem')
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    tex.extension = 'CLIP'
    nt.links.new(nt.nodes.new('ShaderNodeTexCoord').outputs['UV'], tex.inputs['Vector'])
    lum = nt.nodes.new('ShaderNodeRGBToBW')
    nt.links.new(tex.outputs['Color'], lum.inputs[0])
    if style == 'deboss':
        shade = ramp(nt, lum.outputs[0], [(0.0, rgba(leather, 0.25)), (1.0, rgba(leather, 0.7))])
        nt.links.new(shade, bsdf.inputs['Base Color'])
        nt.links.new(math_node(nt, 'MULTIPLY', tex.outputs['Alpha'], 0.92), sock(bsdf.inputs, 'Alpha'))
        nt.links.new(bump(nt, lum.outputs[0], 0.6, 0.004), bsdf.inputs['Normal'])
        set_input(bsdf, 'Roughness', 0.55)
    else:
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        nt.links.new(tex.outputs['Alpha'], sock(bsdf.inputs, 'Alpha'))
        nt.links.new(bump(nt, lum.outputs[0], 0.35, 0.003), bsdf.inputs['Normal'])
        set_input(bsdf, 'Roughness', 0.45)
        set_input(bsdf, 'Metallic', 0.25)
    use_alpha_cutout(mat)
    return mat


# -------------------------------------------------------------------- objects

def link_object(ob, parent=None):
    bpy.context.scene.collection.objects.link(ob)
    if parent is not None:
        bpy.context.view_layer.update()
        ob.parent = parent
        ob.matrix_parent_inverse = parent.matrix_world.inverted()
    return ob


def add_box(bm, x0, x1, y0, y1, z0, z1):
    v = [bm.verts.new(c) for c in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([v[i] for i in f])


def box(name, x0, x1, y0, y1, z0, z1, mat, parent=None, bevel=0.0):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    add_box(bm, x0, x1, y0, y1, z0, z1)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(name, mesh)
    if bevel:
        mod = ob.modifiers.new('Bevel', 'BEVEL')
        mod.width = bevel
        mod.segments = 3
    return link_object(ob, parent)


def quad(name, cx, cy, z, w, h, mat, parent=None):
    """Flat picture plane facing up, UVs 0..1."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(cx - w / 2, cy - h / 2, z), (cx + w / 2, cy - h / 2, z),
                      (cx + w / 2, cy + h / 2, z), (cx - w / 2, cy + h / 2, z)], [], [(0, 1, 2, 3)])
    layer = mesh.uv_layers.new(name='UVMap')
    layer.data.foreach_set('uv', [0, 0, 1, 0, 1, 1, 0, 1])
    mesh.materials.append(mat)
    return link_object(bpy.data.objects.new(name, mesh), parent)


def make_sheet(name, mat, t, z_right, z_left, curl, parent):
    verts = sheet_vertices(t, PAGE_W, PAGE_H, GRID_X, GRID_Y, z_right, z_left, curl=curl, gutter=LAYOUT.gutter)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts.tolist(), [], grid_faces(GRID_X, GRID_Y))
    uvs = grid_uvs(GRID_X, GRID_Y)
    layer = mesh.uv_layers.new(name='UVMap')
    loop_v = np.zeros(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', loop_v)
    layer.data.foreach_set('uv', uvs[loop_v].astype(np.float32).ravel())
    if hasattr(mesh, 'shade_smooth'):
        mesh.shade_smooth()
    else:
        for p in mesh.polygons:
            p.use_smooth = True
    mesh.materials.append(mat)
    ob = link_object(bpy.data.objects.new(name, mesh), parent)
    paper = ob.modifiers.new('Paper', 'SOLIDIFY')
    paper.thickness = 0.0012       # real paper thickness, so the edges read as paper
    paper.offset = -1.0            # extrude downwards; the printed face stays on top
    return ob


def update_sheet(ob, t, z_right, z_left, curl, smoothness=1.0):
    verts = sheet_vertices(t, PAGE_W, PAGE_H, GRID_X, GRID_Y, z_right, z_left, curl=curl,
                           gutter=LAYOUT.gutter, smoothness=smoothness)
    ob.data.vertices.foreach_set('co', verts.astype(np.float32).ravel())
    ob.data.update()


def page_block(name, side, mat, parent):
    """Paper block whose top follows the gutter curve. side = +1 right half, -1 left half."""
    verts, faces = bm.block_prism(LAYOUT, side)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts.tolist(), [], faces)
    mesh.validate()
    mesh.materials.append(mat)
    return link_object(bpy.data.objects.new(name, mesh), parent)


def resting_sheet(name, layout, side, j, count, mat, parent):
    """One real resting sheet: a thin wedge slice of the stack (step 2 real pages)."""
    verts, faces = bm.sheet_slice(layout, side, j, count)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts.tolist(), [], faces)
    mesh.validate()
    mesh.materials.append(mat)
    return link_object(bpy.data.objects.new(name, mesh), parent)


def spine_object(book, leather, parent):
    """Leather strip under the gutter when open, wrapping the book's side when closed."""
    open_pts, closed_pts, faces = bm.spine_shapes(LAYOUT, int(book['spine_bands']))
    mesh = bpy.data.meshes.new('Spine')
    mesh.from_pydata(open_pts.tolist(), [], faces)
    if hasattr(mesh, 'shade_smooth'):
        mesh.shade_smooth()
    mesh.materials.append(leather)
    ob = bpy.data.objects.new('Spine', mesh)
    sol = ob.modifiers.new('Thickness', 'SOLIDIFY')
    sol.thickness = 0.008
    link_object(ob, parent)
    ob.shape_key_add(name='Open')
    key = ob.shape_key_add(name='Closed')
    key.data.foreach_set('co', closed_pts.astype(np.float32).ravel())
    return key


def stitches(name, cx, cy, z, w, h, inset, mat, parent):
    """A row of short thread stitches around a rectangle (the cover's edge)."""
    bm = bmesh.new()
    step, length, width, height = 0.035, 0.022, 0.006, 0.0035
    x0, x1, y0, y1 = cx - w / 2 + inset, cx + w / 2 - inset, cy - h / 2 + inset, cy + h / 2 - inset
    for x in np.arange(x0, x1 - length, step):
        for y in (y0, y1):
            add_box(bm, x, x + length, y - width / 2, y + width / 2, z, z + height)
    for y in np.arange(y0, y1 - length, step):
        for x in (x0, x1):
            add_box(bm, x - width / 2, x + width / 2, y, y + length, z, z + height)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(mat)
    return link_object(bpy.data.objects.new(name, mesh), parent)


def cover_border(name, cx, cy, z, w, h, inset, line, depth, mat, parent, outward=1):
    """A raised decorative frame on a cover face (the tooled border)."""
    bm_ = bmesh.new()
    x0, x1 = cx - w / 2 + inset, cx + w / 2 - inset
    y0, y1 = cy - h / 2 + inset, cy + h / 2 - inset
    t = line
    z0, z1 = (z, z + depth) if outward > 0 else (z - depth, z)
    for a, b, c, d in ((x0, x1, y0, y0 + t), (x0, x1, y1 - t, y1),
                       (x0, x0 + t, y0, y1), (x1 - t, x1, y0, y1)):
        add_box(bm_, a, b, c, d, z0, z1)
    mesh = bpy.data.meshes.new(name)
    bm_.to_mesh(mesh)
    bm_.free()
    mesh.materials.append(mat)
    return link_object(bpy.data.objects.new(name, mesh), parent)


def title_text(book, cx, cy, z, cover_h, parent, leather):
    curve = bpy.data.curves.new('Title', 'FONT')
    curve.body = book['title']
    curve.align_x = 'CENTER'
    curve.align_y = 'CENTER'
    curve.size = book['title_size'] * cover_h
    curve.extrude = 0.0015
    if book['title_style'] == 'gold':
        mat = plain_material('TitleGold', (0.78, 0.52, 0.18), roughness=0.3, metallic=1.0)
    else:
        mat = plain_material('TitlePressed', rgba(leather, 0.3), roughness=0.55)
    curve.materials.append(mat)
    ob = bpy.data.objects.new('Title', curve)
    ob.location = (cx, cy, z)
    return link_object(ob, parent)


def build_book(job):
    """Creates every object. Returns what the frame loop animates."""
    global PAGE_H, LAYOUT, BOOK_POS
    book = job['book']
    images = job['images']
    turns, left_i, sheets, right_i = layout_pages(len(images))
    recorded = job.get('recorded_clips') or []
    page_count = int(job.get('page_count', 50))
    left_count = int(round(job.get('open_at', 0.04) * page_count))
    LAYOUT = L = bm.SheetLayout(book['page_aspect'], page_count, left_count, turns + len(recorded))
    PAGE_H = L.page_h
    m = COVER_MARGIN
    hy = L.cover_h / 2
    hinge_z = L.hinge

    leather = leather_material(book['leather_color'], image=book.get('leather_image'))  # front cover
    back_leather = leather_material(book.get('back_cover_color', book['leather_color']),
                                    name='BackLeather', image=book.get('leather_image'))
    endpaper = leather_material(book.get('inside_cover_color', book['leather_color']),
                                name='InsideLeather',
                                image=book.get('inside_leather_image') or book.get('leather_image'))
    edges = page_edge_material(book)

    root = link_object(bpy.data.objects.new('Book', None))
    tf = job.get('transform') or {}
    BOOK_POS = tuple(float(v) for v in tf.get('pos', (0.0, 0.0, 0.0)))
    root.rotation_euler = tuple(math.radians(float(v)) for v in tf.get('rot', (0.0, 0.0, 0.0)))
    root.scale = tuple(float(v) for v in tf.get('scale', (1.0, 1.0, 1.0)))
    pivot = bpy.data.objects.new('FrontCoverHinge', None)
    pivot.location = (0, 0, hinge_z)
    link_object(pivot, root)

    # Open-book layout. The left half (front cover side) hangs on the hinge.
    hide_pages = bool(job.get('hide_pages'))
    box('CoverRight', 0, PAGE_W + m, -hy, hy, 0, COVER_T, back_leather, root, bevel=0.015)
    quad('EndpaperRight', (PAGE_W + m) / 2, 0, COVER_T + 0.0006, PAGE_W + m, 2 * hy, endpaper, root)
    if not hide_pages:
        for j in range(L.right_rest_count):
            resting_sheet(f'PagesRight{j}', L, 1, j, L.right_rest_count, edges, root)
    box('CoverLeft', -PAGE_W - m, 0, -hy, hy, 0, COVER_T, leather, pivot, bevel=0.015)
    quad('EndpaperLeft', -(PAGE_W + m) / 2, 0, COVER_T + 0.0006, PAGE_W + m, 2 * hy, endpaper, pivot)
    inside_border = plain_material('InsideBorder', rgba(book['leather_color'], 0.35), roughness=0.7)
    for i2, ins in enumerate((0.028, 0.046)):
        cover_border(f'InsideBorderR{i2}', (PAGE_W + m) / 2, 0, COVER_T + 0.0008,
                     PAGE_W + m, 2 * hy, ins, 0.006, 0.0004, inside_border, root, outward=1)
        cover_border(f'InsideBorderL{i2}', -(PAGE_W + m) / 2, 0, COVER_T + 0.0008,
                     PAGE_W + m, 2 * hy, ins, 0.006, 0.0004, inside_border, pivot, outward=1)
    for j in range(L.left_rest_count):
        if not hide_pages:
            resting_sheet(f'PagesLeft{j}', L, -1, j, L.left_rest_count, edges, pivot)
    get = lambda i: images[i] if i is not None else None  # noqa: E731
    curl = job['curl']
    if not hide_pages:
        make_sheet('LeftPage', sheet_material('Left', None, get(left_i), job), 1.0,
                   L.base_left + 0.0015, L.base_left + 0.0015, curl, pivot)
        make_sheet('LastRightPage', sheet_material('LastRight', get(right_i), None, job), 0.0,
                   L.base_right + 0.0015, L.base_right + 0.0015, curl, root)
    moving = []
    if not hide_pages:
        for k, (f, b) in enumerate(sheets):
            zr, zl = L.turn_levels(k)
            ob = make_sheet(f'Sheet{k + 1}', sheet_material(f'Sheet{k + 1}', get(f), get(b), job), 0.0, zr, zl, curl, root)
            moving.append((ob, zr, zl))
        for j in range(len(recorded)):
            k = turns + j
            zr, zl = L.turn_levels(k)
            ob = make_sheet(f'RecSheet{j + 1}', sheet_material(f'RecSheet{j + 1}', None, None, job),
                            0.0, zr, zl, curl, root)
            moving.append((ob, zr, zl))

    spine_key = spine_object(book, leather, root)

    # Front-cover decorations are placed with the book closed, so they read correctly on top.
    pivot.rotation_euler = (0, math.pi, 0)
    bpy.context.view_layer.update()
    cover_w, cover_h = PAGE_W + m, 2 * hy
    cx, z_top = cover_w / 2, 2 * hinge_z
    border_mat = plain_material('TooledBorder', rgba(book['leather_color'], 0.35), roughness=0.7)
    for i, ins in enumerate((0.028, 0.046)):
        cover_border(f'CoverBorder{i}', cx, 0, z_top + 0.0002, cover_w, cover_h, ins,
                     0.006, 0.0004, border_mat, pivot, outward=1)
        cover_border(f'BackBorder{i}', (PAGE_W + m) / 2, 0, 0.0, PAGE_W + m, 2 * hy, ins,
                     0.006, 0.0004, border_mat, root, outward=-1)
    if book['stitching']:
        thread = plain_material('Thread', book['thread_color'], roughness=0.7)
        stitches('Stitching', cx, 0, z_top, cover_w, cover_h, 0.035, thread, pivot)
    if book['emblem']:
        img = load_image(book['emblem'])
        if img is not None:
            size = book['emblem_size'] * cover_w
            w, h = (size, size * img.size[1] / img.size[0])
            em = quad('Emblem', cx, book['emblem_y'] * cover_h, z_top + 0.0012, w, h,
                      emblem_material(img, book['emblem_style'], book['leather_color']), pivot)
            if book['emblem_style'] == 'medallion':
                sol = em.modifiers.new('Thickness', 'SOLIDIFY')
                sol.thickness = 0.004
                sol.offset = 1.0
    if book['title'].strip():
        title_text(book, cx, book['title_y'] * cover_h, z_top + 0.0008, cover_h, pivot, book['leather_color'])

    return turns, moving, root, pivot, spine_key, cover_w


# ------------------------------------------------------------- camera, lights

class Camera:
    """Camera from the app's angle settings; framing is recomputed each frame for slow moves."""

    def __init__(self, job):
        import camera_fit as cf
        self.cf = cf
        self.settings = job['cam']
        self.aspect = job['width'] / job['height']
        top = LAYOUT.camera_top()
        self.target = (0.0, 0.0, top)
        self.book_w, self.book_h = 2 * (PAGE_W + COVER_MARGIN), PAGE_H + 2 * COVER_MARGIN
        self.points = cf.book_points(PAGE_W, PAGE_H, COVER_MARGIN, top)
        data = bpy.data.cameras.new('Camera')
        data.sensor_width = cf.SENSOR
        data.sensor_fit = 'HORIZONTAL'
        data.lens = float(self.settings['lens'])
        data.clip_start = 0.05
        data.clip_end = 200
        self.ob = bpy.data.objects.new('Camera', data)
        bpy.context.scene.collection.objects.link(self.ob)
        bpy.context.scene.camera = self.ob
        self.moving = self.settings.get('move', 'none') != 'none'
        self.place(0.0)

    def place(self, frac):
        cam, r, u, f, lens = self.cf.shot(self.settings, frac, self.target, self.book_w, self.book_h,
                                          self.points, self.aspect)
        rows = self.cf.matrix_rows(cam, r, u, f)
        try:
            from mathutils import Matrix
            rows = Matrix(rows)
        except ImportError:
            pass
        self.ob.matrix_world = rows


def setup_lights(job):
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy = 3.2
    sun_data.color = (1.0, 0.9, 0.78)
    sun_data.angle = math.radians(6)
    sun = bpy.data.objects.new('Sun', sun_data)
    sun.rotation_euler = (math.radians(38), math.radians(-28), math.radians(20))
    bpy.context.scene.collection.objects.link(sun)
    world = bpy.data.worlds.new('World')
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value = (0.32, 0.30, 0.28, 1)
    bg.inputs['Strength'].default_value = 0.55
    bpy.context.scene.world = world


# ------------------------------------------------------------ render settings

def enable_gpu_cycles():
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        refresh = getattr(prefs, 'refresh_devices', None) or prefs.get_devices
        refresh()
        found = [d for d in prefs.devices if d.type == kind]
        if found:
            for d in prefs.devices:
                d.use = d.type == kind
            return kind
    return None


def setup_render(job):
    scene = bpy.context.scene
    r = scene.render
    if job['quality'] == 'cycles':
        r.engine = 'CYCLES'
        kind = enable_gpu_cycles()
        scene.cycles.device = 'GPU' if kind else 'CPU'
        scene.cycles.samples = int(job.get('samples', 96))
        scene.cycles.use_denoising = True
        log(f'INFO Cycles on {kind or "CPU (no GPU found)"}')
    else:
        for name in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
            try:
                r.engine = name
                break
            except TypeError:
                continue
        scene.eevee.taa_render_samples = 8 if job['quality'] == 'draft' else 48
        # Contact shadows: soft occlusion where sheets and covers meet.
        for attr, val in (('use_gtao', True), ('gtao_distance', 0.02), ('gtao_factor', 1.0),
                          ('use_fast_gi', True)):
            try:
                setattr(scene.eevee, attr, val)
            except AttributeError:
                pass
        log(f'INFO {r.engine}')
    r.film_transparent = True
    r.resolution_x, r.resolution_y = job['width'], job['height']
    r.resolution_percentage = 100
    r.fps = int(job['fps'])
    img = r.image_settings
    img.file_format = 'PNG'
    img.color_mode = 'RGBA'
    img.color_depth = '8'
    img.compression = int(job.get('png_compression', 15))  # low = faster saving
    scene.view_settings.view_transform = 'Standard'


# ------------------------------------------------------------------------ main

def main():
    job_path = sys.argv[sys.argv.index('--') + 1]
    with open(job_path, encoding='utf-8') as fh:
        job = json.load(fh)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_render(job)
    turns, moving, root, pivot, spine_key, cover_w = build_book(job)
    camera = Camera(job)
    setup_lights(job)

    sc = scene.Scene(turns, job['book']['page_aspect'], job.get('open_at', 0.04), job['fps'],
                     job['start_hold'], job['turn_seconds'], job['pause'], job['end_hold'],
                     job.get('open_seconds', 0.0), job.get('slide', True),
                     page_count=job.get('page_count'), smoothness=job.get('smoothness', 1.0),
                     recorded_clips=job.get('recorded_clips'), clip_list=job.get('clip_list'))
    frames = job.get('frames') or list(range(sc.frames))
    out = job['out_dir']
    os.makedirs(out, exist_ok=True)
    last_t = [None] * len(moving)
    started = time.time()
    log(f'TOTAL {len(frames)}')
    for i, f in enumerate(frames):
        pose = sc.evaluate(f)
        if camera.moving:
            camera.place(pose['camera_frac'])
        angle, slide = pose['cover_angle'], pose['cover_slide']
        pivot.rotation_euler = (0, angle, 0)
        spine_key.value = angle / math.pi
        root.location = (slide + BOOK_POS[0], BOOK_POS[1], BOOK_POS[2])
        for k, (ob, zr, zl) in enumerate(moving):
            t = pose['sheet_progress'][k] if k < len(pose['sheet_progress']) else 1.0
            if t != last_t[k]:
                update_sheet(ob, t, zr, zl, job['curl'], smoothness=pose['smoothness'])
                last_t[k] = t
        bpy.context.scene.frame_current = f
        bpy.context.scene.render.filepath = os.path.join(out, f'frame_{i:06d}.png')
        bpy.ops.render.render(write_still=True)
        log(f'PROGRESS {i + 1} {len(frames)}')

    with open(os.path.join(out, 'sequence.json'), 'w', encoding='utf-8') as fh:
        json.dump(dict(width=job['width'], height=job['height'], fps=job['fps'], frames=len(frames),
                       turns=turns, seconds=round(len(frames) / job['fps'], 3), alpha=True,
                       render_seconds=round(time.time() - started, 1)), fh, indent=2)
    log('DONE')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # report clearly to the app, then exit non-zero
        import traceback
        traceback.print_exc()
        log(f'ERROR {exc}')
        sys.stdout.flush()
        os._exit(1)
