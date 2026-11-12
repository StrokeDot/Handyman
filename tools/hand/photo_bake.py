"""Paint Alejandro's two hand photos onto the 3D hand: the back photo on the back of the hand, the
palm photo on the palm. Matching joints on each photo and on the 3D hand say where every bit of skin
comes from (a smooth 'thin-plate' warp between them). The photos' own lighting is taken out
(their large light-and-shadow areas are evened out) so the 3D lights can do that job, while the
wrinkles, veins, hair, creases and nails stay."""
import numpy as np
from PIL import Image
from scipy.interpolate import RBFInterpolator
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates

import landmarks as L

ORDER = ('thumb', 'index', 'middle', 'ring', 'pinky')


def _lum(a):
    return a[..., 0] * 0.30 + a[..., 1] * 0.59 + a[..., 2] * 0.11


def _prepare(path, mask_path, cuff, sigma_share=0.02):
    """(evened-out colour, fine-detail height, skin mask) of one photo. Outside the skin (the
    background and the sleeve) the skin is continued as a mirror image of the skin next to it."""
    rgb = np.asarray(Image.open(path).convert('RGB')).astype(np.float32) / 255.0
    alpha = np.asarray(Image.open(mask_path).convert('RGBA'))[..., 3] > 128
    h, w = alpha.shape
    yy, xx = np.mgrid[0:h, 0:w]
    (ax, ay), (bx, by) = cuff
    side = (bx - ax) * (yy - ay) - (by - ay) * (xx - ax)          # > 0: the sleeve's side of the line
    from scipy.ndimage import binary_erosion
    ln = np.hypot(bx - ax, by - ay)
    dist = side / ln                                              # signed distance from the cuff line
    skin = binary_erosion(alpha & (dist < -25), iterations=14)
    # past the cuff: mirror the wrist's skin across the cuff line (no seam)
    nx, ny = -(by - ay) / ln, (bx - ax) / ln
    k = 2 * np.maximum(dist + 25, 0)
    my = np.clip(np.round(yy - k * ny), 0, h - 1).astype(int)
    mx = np.clip(np.round(xx - k * nx), 0, w - 1).astype(int)
    by_mirror = (dist >= -25) & skin[my, mx]
    sy0, sx0 = np.where(by_mirror, my, yy), np.where(by_mirror, mx, xx)
    have = skin | by_mirror
    # everywhere else (around the fingers): the nearest skin, mirrored outwards
    d, (iy, ix) = distance_transform_edt(~have, return_indices=True)
    ry, rx = np.clip(2 * iy - yy, 0, h - 1), np.clip(2 * ix - xx, 0, w - 1)
    good = have[ry, rx]
    ty, tx = np.where(good, ry, iy), np.where(good, rx, ix)
    sy, sx = np.where(have, sy0, sy0[ty, tx]), np.where(have, sx0, sx0[ty, tx])
    rgb = rgb[sy, sx]
    lum = _lum(rgb) + 1e-3
    big = gaussian_filter(lum, sigma_share * w)
    target = float(np.median(lum[skin]))
    even = np.clip(rgb * (target / big)[..., None], 0, 1)
    fine = lum / gaussian_filter(lum, 0.006 * w)              # wrinkles and pores, about 1.0 on average
    return even, fine, skin


def _sample(img, xy):
    return np.stack([map_coordinates(img[..., c] if img.ndim == 3 else img, [xy[:, 1], xy[:, 0]], order=1,
                                     mode='nearest') for c in range(img.shape[2] if img.ndim == 3 else 1)], 1)


def bake(P, N, UVs, polys, joints, wrist, right, fwd, up, back_path, palm_path, back_mask, palm_mask, res,
         out_colour, out_height):
    """P, N: rest vertex positions and normals; UVs: per-loop UVs; polys: [(verts, loops)];
    joints: finger -> [tip, DIP, PIP, MCP] 3D points (thumb: tip, IP, MCP, base)."""
    right, fwd, up = (np.array(v) / np.linalg.norm(v) for v in (right, fwd, up))

    def plane(x):
        return np.stack([x @ right, x @ fwd], -1)

    side_dir = np.array(joints['index'][3]) - np.array(joints['pinky'][3])
    side_dir = side_dir - up * (side_dir @ up)
    side_dir /= np.linalg.norm(side_dir)
    rel = P - np.array(wrist)
    near = np.abs(rel @ fwd) < 0.006
    half_t = (rel[near] @ side_dir).max()        # the wrist's thumb side and little-finger side
    half_p = -(rel[near] @ side_dir).min()
    w3 = np.array(wrist)
    model = [plane(np.array(joints[f][k])) for f in ORDER for k in range(4)] + [
        plane(w3), plane(w3 + side_dir * half_t), plane(w3 - side_dir * half_p)]
    model = np.array(model)
    back_pts = [np.array(L.FINGERS[f][k][0]) * 1.254 for f in ORDER for k in range(4)]
    back_pts += [np.array(p, float) for p in L.BACK_WRIST3]
    palm_pts = []
    for f in ORDER:
        tip, dip, pip, mcp = (np.array(p, float) for p in L.PALM_FINGERS[f])
        if f != 'thumb':
            mcp = mcp + (mcp - pip) * 0.35        # the joint sits below the crease at the finger's base
        palm_pts += [tip, dip, pip, mcp]
    palm_pts += [np.array(L.PALM_WRIST, float), np.array(L.PALM_WRIST_THUMB, float),
                 np.array(L.PALM_WRIST_PINKY, float)]
    to_back = RBFInterpolator(model, np.array(back_pts), kernel='thin_plate_spline', smoothing=1e-6)
    to_palm = RBFInterpolator(model, np.array(palm_pts), kernel='thin_plate_spline', smoothing=1e-6)

    b_even, b_fine, b_skin = _prepare(back_path, back_mask, L.BACK_CUFF)
    p_even, p_fine, p_skin = _prepare(palm_path, palm_mask, L.PALM_CUFF)
    p_even = 0.55 * p_even + 0.45 * gaussian_filter(p_even, (6, 6, 0))      # the palm photo's creases are very strong
    p_fine = 1 + (p_fine - 1) * 0.6
    def desat(a, k=0.82):
        g = a.mean(-1, keepdims=True)
        return np.clip(g + (a - g) * k, 0, 1)
    b_even = desat(b_even)
    back_mean = b_even[b_skin].mean(0)
    palm_tone = back_mean * np.array([1.10, 1.04, 1.0]) * 1.06    # palms are lighter and a little pinker
    p_col = np.clip(palm_tone * (p_even.mean(-1, keepdims=True) / p_even[p_skin].mean()), 0, 1)

    colour = np.zeros((res, res, 3), np.float32)
    height = np.zeros((res, res), np.float32)
    filled = np.zeros((res, res), bool)
    for verts, loops in polys:
        for k in range(1, len(verts) - 1):
            tri = [0, k, k + 1]
            uv3 = UVs[[loops[i] for i in tri]] * res
            p3, n3 = P[[verts[i] for i in tri]], N[[verts[i] for i in tri]]
            x0, y0 = np.floor(uv3.min(0)).astype(int) - 1
            x1, y1 = np.ceil(uv3.max(0)).astype(int) + 1
            xs, ys = np.meshgrid(np.arange(max(x0, 0), min(x1, res)), np.arange(max(y0, 0), min(y1, res)))
            q = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], 1)
            T = np.array([uv3[1] - uv3[0], uv3[2] - uv3[0]]).T
            if abs(np.linalg.det(T)) < 1e-9:
                continue
            l12 = np.linalg.solve(T, (q - uv3[0]).T).T
            bary = np.column_stack([1 - l12.sum(1), l12])
            ok = (bary > -0.01).all(1)
            if not ok.any():
                continue
            b = bary[ok]
            x, n = b @ p3, b @ n3
            n = n / np.linalg.norm(n, axis=1, keepdims=True)
            s = n @ up
            wb = np.clip((s + 0.25) / 0.5, 0, 1)                 # facing up: the back photo
            wp = 1 - wb
            xy = plane(x)
            cb, cp = _sample(b_even, to_back(xy)), _sample(p_col, to_palm(xy))
            hb, hp = _sample(b_fine, to_back(xy))[:, 0], _sample(p_fine, to_palm(xy))[:, 0]
            yy, xx = ys.ravel()[ok], xs.ravel()[ok]
            col = cb * wb[:, None] + cp * wp[:, None]
            # round the sides the photos are seen edge-on (stretched): plain skin tone instead
            seen = np.clip((np.abs(s) - 0.12) / 0.35, 0, 1)[:, None]
            tone = np.where(s[:, None] > 0, back_mean[None, :], palm_tone[None, :])
            colour[yy, xx] = col * seen + tone * (1 - seen)
            height[yy, xx] = hb * wb + hp * wp
            filled[yy, xx] = True
    # spread the edges of each piece outwards a little, so no seams show
    idx = distance_transform_edt(~filled, return_distances=False, return_indices=True)
    colour, height = colour[idx[0], idx[1]], height[idx[0], idx[1]]
    # clean, even skin: soften speckle and blotches, keep the broad colour (knuckles, palm)
    soft = gaussian_filter(colour, (1.2, 1.2, 0))
    broad = gaussian_filter(colour, (res * 0.012, res * 0.012, 0))
    colour = np.clip(broad + (soft - broad) * float(__import__('os').environ.get('SKIN_DETAIL', 0.45)), 0, 1)
    Image.fromarray((colour[::-1] * 255).astype(np.uint8)).save(out_colour)
    hmap = np.clip((height - 1.0) * 2.5 + 0.5, 0, 1)
    Image.fromarray((hmap[::-1] * 255).astype(np.uint8)).save(out_height)
    return out_colour, out_height
