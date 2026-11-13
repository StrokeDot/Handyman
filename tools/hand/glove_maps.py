"""Arthur Morgan style leather gloves for the hand (step 7): pictures on the hand's own UV map, made
from the hand mesh itself (no outside pictures), so the glove fits the hand exactly:

    live_glove_albedo.png     dark, worn brown leather - lighter and greyer where it rubs (the
                              knuckles, the finger tips and pads), darker in the creases
    live_glove_normal.png     its relief: pebbled grain, creases across every finger joint,
                              stitched seams along the fingers' sides, the hem's rolled edge
    live_glove_rough_ao.png   red: shadowing (the hand's baked AO), green: roughness (worn spots
                              polished, creases dull)

    python3 glove_maps.py resources/hand/hand.blend [size] [--repair-skin]
--repair-skin first fills the skin's own baked pictures past their islands' edges (once, after
live_maps.py: the bake leaves them black there, which shows as dark squares in the live view).
The glove ends a few cm past the wrist (under the coat's cuff); beyond it the skin's own picture.
"""
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

HEM_CM = 5.0            # the glove reaches this far past the wrist towards the elbow
LEATHER = np.array((0.155, 0.112, 0.082))        # dark brown leather (as RDR2's, in the live view)
WORN = np.array((0.36, 0.30, 0.25))              # rubbed pale grey-brown
CREASE = np.array((0.075, 0.055, 0.042))


def raster(ob, size):
    """Per texel: the rest position (metres, mesh space) of the surface there, and a mask - from
    the mesh as the live view draws it (smoothed once: its picture coordinates shift a little)."""
    keep = {m.name: m.show_viewport for m in ob.modifiers}
    for m in ob.modifiers:
        m.show_viewport = m.type == 'SUBSURF'
        if m.type == 'SUBSURF':
            m.levels = 1
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    me.calc_loop_triangles()
    uvl = me.uv_layers['hand'].data
    P = np.zeros((size, size, 3), np.float32)
    N = np.zeros((size, size, 3), np.float32)
    M = np.zeros((size, size), bool)
    co = np.array([v.co[:] for v in me.vertices], np.float32)
    nr = np.array([v.normal[:] for v in me.vertices], np.float32)
    for tri in me.loop_triangles:
        uv = np.array([uvl[li].uv[:] for li in tri.loops], np.float64) * size     # (u right, v up)
        vs = list(tri.vertices)
        x0, y0 = np.floor(uv.min(0)).astype(int)
        x1, y1 = np.ceil(uv.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax, ay), (bx, by), (cx, cy) = uv
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / den
        w1 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / den
        w2 = 1 - w0 - w1
        ins = (w0 >= -1e-3) & (w1 >= -1e-3) & (w2 >= -1e-3)
        if not ins.any():
            continue
        W = np.stack([w0[ins], w1[ins], w2[ins]], 1)
        rr, cc = (ys[ins] - 0.5).astype(int), (xs[ins] - 0.5).astype(int)
        P[rr, cc] = W @ co[vs]
        N[rr, cc] = W @ nr[vs]
        M[rr, cc] = True
    ev.to_mesh_clear()
    for m in ob.modifiers:
        m.show_viewport = keep[m.name]
    return P, N, M


def fill_out(a, mask, steps=12):
    """Spread values past the islands' edges (no dark seams when the picture is filtered)."""
    from scipy import ndimage
    idx = ndimage.distance_transform_edt(~mask, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def periodic_noise(n, scale, rng):
    f = np.fft.fftfreq(n)
    fx, fy = np.meshgrid(f, f)
    r = np.sqrt(fx ** 2 + fy ** 2) * n
    x = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * np.exp(-(r / scale) ** 2)))
    return (x - x.mean()) / (x.std() + 1e-9)


def repair_skin_maps(out_dir):
    """The skin's baked pictures (live_maps.py) were baked a little inside the picture's islands,
    black beyond: the live view's smoothed hand samples there in places (dark squares). Spread
    each picture outwards from its baked texels (from well inside, past the bake's own edge)."""
    from PIL import Image
    from scipy import ndimage
    alb = np.asarray(Image.open(os.path.join(out_dir, 'live_albedo.png')).convert('RGB'), np.float32)
    valid = ndimage.binary_erosion(alb.sum(2) > 12.0, iterations=2)
    for name in ('live_albedo.png', 'live_normal.png', 'live_rough_ao.png'):
        path = os.path.join(out_dir, name)
        px = np.asarray(Image.open(path).convert('RGB'))
        Image.fromarray(np.ascontiguousarray(fill_out(px, valid))).save(path, optimize=True)
        print('repaired', name, flush=True)


def main():
    from PIL import Image
    from scipy import ndimage
    args = [a for a in sys.argv[1:] if a != '--']
    blend = args[0]
    size = int(args[1]) if len(args) > 1 and args[1].isdigit() else 2048
    out_dir = os.path.dirname(os.path.abspath(blend))
    if '--repair-skin' in sys.argv:
        repair_skin_maps(out_dir)
    bpy.ops.wm.open_mainfile(filepath=blend)
    ob = bpy.data.objects['Hand']
    rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    to_mesh = ob.matrix_world.inverted() @ rig.matrix_world
    bone = {b.name: (to_mesh @ b.head_local, to_mesh @ b.tail_local) for b in rig.data.bones}
    P, Nrm, M = raster(ob, size)
    print('texels on the hand', int(M.sum()), flush=True)
    wrist = np.array(bone['hand_r'][0])
    elbow = np.array(bone['lowerarm_r'][0])
    axis = (wrist - elbow) / np.linalg.norm(wrist - elbow)
    t = (P - wrist) @ axis * 100.0                                  # cm past the wrist (+ towards the fingers)
    # (the back of the hand's side: from the palm towards the back)
    side = np.array(bone['index_01_r'][0]) - np.array(bone['pinky_01_r'][0])
    fwd = np.array(bone['middle_01_r'][0]) - wrist
    up = np.cross(fwd, side)
    up /= np.linalg.norm(up)
    back = (Nrm @ up)                                               # +1 back of the hand, -1 palm
    glove = M & (t > -HEM_CM)
    # ---- joints: distance to each finger joint, and how far along the finger past it
    crease_h = np.zeros((size, size), np.float32)
    wear = np.zeros((size, size), np.float32)
    on_finger = np.zeros((size, size), bool)                        # (seams run along the fingers only)
    for f in ('thumb', 'index', 'middle', 'ring', 'pinky'):
        for k in (1, 2, 3):
            h0, h1 = (np.array(v) for v in bone[f'{f}_0{k}_r'])
            ax = (h1 - h0) / (np.linalg.norm(h1 - h0) + 1e-9)
            d = P - h0
            along = d @ ax * 100.0                                  # cm along the finger from the joint
            radial = np.linalg.norm(d - np.outer(d.reshape(-1, 3) @ ax, ax).reshape(d.shape), axis=2) * 100.0
            near = np.exp(-(along / (0.55 if k > 1 else 0.8)) ** 2) * (radial < 1.6)
            seg = np.linalg.norm(h1 - h0) * 100.0
            on_finger |= (along > (0.4 if k == 1 else -0.2)) & (along < seg + 0.3) & (radial < 1.3) & (f != 'thumb' or k > 1)
            # creases: fine ridges across the finger at the joint, deeper on the palm side
            depth = 0.6 + 0.4 * np.clip(-back, 0, 1)
            crease_h += near * depth * (0.5 + 0.5 * np.cos(along * 2 * np.pi / 0.32))
            if k == 1 or k == 2:                                    # knuckles rub pale on the back
                wear += np.exp(-(along / 0.9) ** 2 - (radial / 1.6) ** 2 * 0.0) * np.clip(back, 0, 1) * (radial < 1.8)
        tip = np.array(bone[f'{f}_03_r'][1])
        dt = np.linalg.norm(P - tip, axis=2) * 100.0
        wear += np.exp(-(dt / 1.1) ** 2) * 1.2                      # finger ends and pads
    wear += 0.35 * np.exp(-((t - 6.0) / 3.0) ** 2) * np.clip(-back, 0, 1)   # the palm's heel
    rng = np.random.default_rng(11)
    mott = periodic_noise(size, size / 60.0, rng)
    wear = np.clip(wear * (0.75 + 0.35 * mott), 0, 1) * glove
    # ---- grain: pebbled leather (cells), a finer pore, and broad wrinkles
    grain = np.abs(periodic_noise(size, size / 9.0, rng))           # ~0.5 mm pebbles
    pore = periodic_noise(size, size / 3.5, rng)
    broad = periodic_noise(size, size / 120.0, rng)
    # ---- seams: stitched lines along the islands' edges (the fingers' sides), inside the glove
    dist = ndimage.distance_transform_edt(M)                        # texels from an island's edge
    mm = 1.0 / (0.022 * size / 100.0) if False else None
    tex_mm = 0.1 * size / 2048.0 * 22.0                             # (about 4.5 texels per mm at 2048)
    on_finger &= np.abs(back) < 0.55                                # (the fingers' sides, not their backs)
    seam = glove & (dist > 0) & (dist < 2.4 * tex_mm) & on_finger
    groove = np.exp(-((dist - 1.6 * tex_mm) / (0.45 * tex_mm)) ** 2) * seam
    yy, xx = np.mgrid[0:size, 0:size]
    stitch = (np.sin((xx + yy) * 2 * np.pi / (3.2 * tex_mm)) > 0.2) * np.exp(-((dist - 2.6 * tex_mm) / (0.5 * tex_mm)) ** 2) * glove * on_finger
    # ---- the hem: a rolled edge, then the skin beyond
    hem = np.exp(-((t + HEM_CM - 0.35) / 0.25) ** 2) * M
    # ---- height and normal (texels: rows are v upwards, as built)
    h = (0.55 * grain + 0.18 * pore + 0.35 * broad) * glove
    h += 2.2 * crease_h * glove
    h -= 3.0 * groove
    h += 1.6 * stitch
    h += 3.5 * hem
    h = ndimage.gaussian_filter(h, 0.7)
    gy, gx = np.gradient(h)
    k = 0.9
    n = np.stack([-gx * k, -gy * k, np.ones_like(h)], 2)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    # ---- colour, roughness
    shade = 1.0 + 0.10 * broad + 0.06 * pore - 0.25 * np.clip(crease_h, 0, 1)
    col = LEATHER[None, None, :] * shade[..., None]
    col = col * (1 - wear[..., None]) + WORN[None, None, :] * (0.85 + 0.2 * grain[..., None]) * wear[..., None]
    col = col * (1 - 0.6 * np.clip(crease_h, 0, 1)[..., None]) + CREASE * 0.6 * np.clip(crease_h, 0, 1)[..., None]
    col = col * (1 - 0.5 * groove[..., None])
    col = col + np.array((0.42, 0.36, 0.28)) * 0.45 * stitch[..., None]      # pale thread
    skin = np.asarray(Image.open(os.path.join(out_dir, 'live_albedo.png')).convert('RGB'), np.float32)[::-1] / 255.0
    edge = np.clip((t + HEM_CM) / 0.15, 0, 1)[..., None]                       # glove .. skin at the hem
    col = col * edge + skin * (1 - edge)
    ra_skin = np.asarray(Image.open(os.path.join(out_dir, 'live_rough_ao.png')).convert('RGB'), np.float32)[::-1] / 255.0
    rough = 0.62 - 0.22 * wear + 0.15 * np.clip(crease_h, 0, 1) + 0.04 * pore
    rough = rough * edge[..., 0] + ra_skin[..., 1] * (1 - edge[..., 0])
    ao = ra_skin[..., 0]
    n = n * edge + np.array((0.0, 0.0, 1.0)) * (1 - edge)
    # (outside the islands: copied from well inside the nearest island - never its seams or a
    # neighbour's - so a texel just past an edge looks like plain leather there)
    inner = ndimage.binary_erosion(M, iterations=4)
    col, rough, ao = fill_out(col, inner), fill_out(rough, inner), fill_out(ao, inner)
    n = np.where(M[..., None] & inner[..., None], n, np.where(M[..., None], n, np.array((0.0, 0.0, 1.0))))
    near_edge = M & ~inner
    n[near_edge] = n[near_edge] * 0.4 + np.array((0.0, 0.0, 0.6))
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    col[near_edge] = fill_out(col, inner)[near_edge] * 0.5 + col[near_edge] * 0.5

    def save(px, name):
        a = np.clip(px[::-1] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        Image.fromarray(a).save(os.path.join(out_dir, name), optimize=True)
        print('wrote', name, flush=True)
    save(np.clip(col, 0, 1), 'live_glove_albedo.png')
    save(n * 0.5 + 0.5, 'live_glove_normal.png')
    save(np.stack([ao, np.clip(rough, 0, 1), np.zeros_like(ao)], 2), 'live_glove_rough_ao.png')
    _ = (Vector, mm)


if __name__ == '__main__':
    main()
