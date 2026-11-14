"""The right hand moved by Arthur Morgan's own motion, captured from Red Dead Redemption 2's journal.

resources/hand/rdr2_turns.npz holds the two page turns as the game plays them, measured from a
recording of the journal (the hand tracked in every frame, placed on the book, and averaged over
the many times each turn is repeated - see tools/hand/capture_rdr2.md): for each 30th of a second,
where the thumb and index fingertips are on the spread (u: -1 left edge, 0 spine, 1 right edge;
v: 0 bottom, 1 top of the page), where the knuckles are, and which way the hand points.

  forward turn: from resting on the right edge the fingertips take the edge, rise and swing over
                the spine with the page, land on the left page, and come back low along the bottom
  turn back:    low along the bottom to the left page's lower corner, take it, bring it back over
                to the right and let it go there, back to resting

Here the captured path and timing drive the hand. While it holds a page its fingers are put on
the app's own page (so the hand never floats beside it); the hand's tilt comes from three poses per
turn (taking hold, letting go, moving over the pages) blended smoothly - the hand never turns over
with the page. The page's own movement (the clip) sets the speed of the part where the page moves;
the hand's reaching and coming back are the game's, a little slower.
"""
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector

import hand_scene as HS
import journal_geom as G

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'resources', 'hand', 'rdr2_turns.npz')
SLOW = 1.7                  # the hand's own moves (reaching, coming back) this much slower than in the game
HOVER_CM = 1.0              # moving over the pages the finger pads stay this far above them
ON_S = 0.08                 # (game seconds) to take hold of / let go of the page
REST_S = 0.12               # (game seconds) to leave / settle into the resting grip
FREE_DIR = (-0.45, 0.9)     # ...its fingers pointing up the book and a little left (as in the game)
REST_NEAR = (0.06, 0.2)     # the captured fingertips this near the resting spot (spread units): resting
FREE_FINGERS = -0.55        # moving over the pages the hand is open and nearly flat
LET_GO_DEG = 112.0          # turning a page back: let go once it has turned this far (it falls by itself)
GRIP_UP = 0.2               # holding a page: this share up from its bottom edge (the bottom corner)
STAND_ALONG = 0.5           # ...and with the page standing up, at this share of its width from the spine
CLEAR_CM = 0.7              # holding a page, every part of the hand but the thumb stays this far behind it
EDGE_IN = 0.012             # holding a page: this far in from its free edge (share of its width)


def load():
    d = np.load(DATA)
    return {k: d[k] for k in d.files}


def _turns(progs, thetas, n_frames):
    """(thing, first frame, last frame, way) for every page (and the cover) that moves."""
    out = []
    n_sheets = len(progs[0][0]) if progs else 0
    for k in range(n_sheets):
        s = [p[0][k] for p in progs]
        f = 1
        while f < n_frames:
            if abs(s[f] - s[f - 1]) < 1e-6:
                f += 1
                continue
            start, way, end = f - 1, (1 if s[f] > s[f - 1] else -1), f
            while end + 1 < n_frames and abs(s[end + 1] - s[end]) >= 1e-6:
                end += 1
            out.append((k, start, end, way))
            f = end + 1
    if thetas and thetas[0] < math.pi - 1e-3:
        c0 = next((f for f, th in enumerate(thetas) if th > 1e-3), None)
        if c0 is not None:
            c1 = next((f for f, th in enumerate(thetas) if f > c0 and th >= math.pi * 0.99), n_frames - 1)
            out.append(('cover', c0, c1, 1))
    out.sort(key=lambda t: t[1])
    return out


def _series(T, t0, fps, t):
    """The captured values at game time t (s), interpolated (held at the ends)."""
    x = (t - t0) * fps
    i = int(math.floor(x))
    i = min(max(i, 0), len(T) - 2)
    w = min(max(x - i, 0.0), 1.0)
    return T[i] * (1 - w) + T[i + 1] * w


def plan_rdr2(hand, n_frames, fps, state_at, strap_u=None, held_up=False):
    """Poses for every frame [(point, fwd, up, finger amount, anchor)], as hand_scene.plan()."""
    D = load()
    state_at = HS._cached_state(state_at)
    cm = 1.0 / hand.pw
    progs = [state_at(f) for f in range(n_frames)]
    thetas = [p[2] if len(p) > 2 else math.pi for p in progs]
    n_sheets = len(progs[0][0]) if progs else 0
    turns = _turns(progs, thetas, n_frames)
    rest_up = float(np.clip(D['rest'][1], 0.08, 0.8))
    rest_uv = (float(D['rest'][0]), float(D['rest'][1]))

    def to_book(u, v, z):
        return np.array((u, -hand.half_h + v * 2 * hand.half_h, z))

    def turned(f):
        return sum(1 for t in progs[f][0] if t >= 0.5)

    def surface(f, x, v):
        """The top page's height under (x, v) at frame f (left or right of the spine)."""
        ts, cw = state_at(f)[:2]
        if thetas[f] < math.pi * 0.99:
            return float(hand.cover_at(thetas[f], min(1.0, abs(x)), v, 1.0)[0][2])
        n_t = turned(f)
        k = n_t if x >= 0 else n_t - 1
        if not (0 <= k < n_sheets):
            return 0.0
        pt, _ = hand.page_at(k, ts[k], cw[k], min(1.0, abs(x)), v)
        return float(pt[2])

    def thing_at(k, f, along, up):
        ts, cw = state_at(f)[:2]
        if k == 'cover':
            return hand.cover_at(thetas[f], along, up, 0.5)
        return hand.page_at(k, ts[k], cw[k], along, up)

    def raw_angle(k, f):
        _, fr = thing_at(k, f, 0.6, 0.4)
        n = fr[2]
        th = math.atan2(-float(n[0]), float(n[2])) % (2 * math.pi)   # (-180 is 180: a page lying turned over)
        return min(th, math.pi) if th < 1.5 * math.pi else 0.0

    start_angle = {}

    def angle(k, f, way):
        """How far thing k has turned at frame f since its turn began (radians, 0 .. pi)."""
        s0 = next((t[1] for t in turns if t[0] == k and t[3] == way and t[1] <= f), f)
        if (k, s0) not in start_angle:
            start_angle[(k, s0)] = raw_angle(k, s0)
        return min(math.pi, abs(raw_angle(k, f) - start_angle[(k, s0)]))

    def edge_grip(pt, fr):
        """Holding an edge between thumb (on top) and fingers (under), as at rest."""
        p, e_in, n = np.array(pt), np.array(fr[0]), np.array(fr[2])
        target = p + e_in * (HS.KEY_EDGE_IN_CM if held_up else HS.KEY_EDGE_IN_TABLE_CM) * cm
        if held_up:
            target = target - n * 0.5 * cm
        pose = hand.edge_clamp(target, -n, e_in - n * 0.35 + np.array((0.0, 0.15, 0.0)), wrist_at=HS.KEY_EDGE_WRIST_CM)
        return [tuple(np.array(pose[0]) + n * HS.HOLD_LIFT_CM * cm)] + list(pose[1:])

    rest_cache = {}

    def rest_pose(f):
        """Resting on the right edge of whatever is on top (the cover, the next page, the back board)."""
        closed = thetas[f] < math.pi * 0.99
        key = (closed, turned(f))
        if key not in rest_cache:
            if closed:
                pt, fr = hand.cover_at(0.0, 1.0, rest_up, 0.5)
            elif turned(f) >= n_sheets:
                pt, fr = hand.page_at(n_sheets - 1, 0.0, 0.0, 1.0, rest_up)
                pt = np.array(pt) - np.array(fr[2]) * G.PITCH
            else:
                ts, cw = state_at(f)[:2]
                k = turned(f)
                pt, fr = hand.page_at(k, ts[k], cw[k], 1.0, rest_up)
            rest_cache[key] = edge_grip(pt, fr)
        return rest_cache[key]

    def free_pose(f, row):
        """Moving over the pages, open and nearly flat, pointing the way the game's hand points."""
        u, v = float(row[0]), float(row[1])
        dx, dy = FREE_DIR   # (the captured direction is reliable only while the hand lies on a page)
        z = max(surface(f, u, min(max(v, 0.0), 1.0)), 0.0) + HOVER_CM * cm
        fwd = Vector((dx, dy, -0.3)).normalized()
        up = Vector((0.0, 0.0, 1.0))
        up = (up - fwd * up.dot(fwd)).normalized()
        return [tuple(to_book(u, v, z)), tuple(fwd), tuple(up), FREE_FINGERS, 1.0]

    def mix(a, b, w):
        """Between two poses (the hand's turn by the shortest way)."""
        if w <= 0:
            return list(a)
        if w >= 1:
            return list(b)
        m = HS._slerp_m(HS._frame(a[1], a[2]), HS._frame(b[1], b[2]), w)
        p = np.array(a[0]) * (1 - w) + np.array(b[0]) * w
        return [tuple(p), tuple(m.col[0]), tuple(m.col[1]), a[3] + (b[3] - a[3]) * w, a[4] + (b[4] - a[4]) * w]

    # ---- keeping the hand off the page it holds: all of it but the thumb behind the page
    skin = next((o for o in hand.objects if o.type == 'MESH' and not o.name.startswith('Sleeve')), None)
    root_inv = hand.rig.parent.matrix_world.inverted() if hand.rig.parent else Matrix.Identity(4)
    sample, not_thumb = None, None
    if skin is not None:
        gname = {g.index: g.name for g in skin.vertex_groups}
        kind = [gname.get(max(v.groups, key=lambda x: x.weight).group, '') if v.groups else '' for v in skin.data.vertices]
        sample = np.arange(len(kind))[::3]
        not_thumb = np.array([not kind[i].startswith(('thumb_02', 'thumb_03')) for i in sample])

    def keep_off(k, f, pose, way):
        if skin is None:
            return pose
        ts, cw = state_at(f)[:2]
        alongs, ups = [0.03 + 0.94 * i / 10 for i in range(11)], [0.03 + 0.94 * j / 12 for j in range(13)]
        if k == 'cover':
            pts = [hand.cover_at(thetas[f], a_, u_, 0.5) for a_ in alongs for u_ in ups]
            Gp = np.array([p_[0] for p_ in pts]); Gn = np.array([p_[1][2] for p_ in pts])
        else:
            g = G.sheet_state(k, ts[k], cw[k])
            cols = [HS._surface_column(g, a_, ups) for a_ in alongs]
            Gp = np.concatenate([c_[0] for c_ in cols]); Gn = np.concatenate([c_[1] for c_ in cols])
        # (the thumb on the page's front, the rest of the hand behind it, whichever way it turns)
        spacing = max(np.linalg.norm(Gp[1] - Gp[0]), np.linalg.norm(Gp[len(ups)] - Gp[0])) + 1e-9
        mods = [m_ for m_ in skin.modifiers if m_.type == 'SUBSURF']
        for m_ in mods:
            m_.show_viewport = False
        try:
            for _ in range(3):
                hand.apply(pose)
                bpy.context.view_layer.update()
                ev = skin.evaluated_get(bpy.context.evaluated_depsgraph_get())
                me = ev.to_mesh()
                co = np.empty(len(me.vertices) * 3, np.float32)
                me.vertices.foreach_get('co', co)
                ev.to_mesh_clear()
                Ms = np.array(root_inv @ skin.matrix_world)
                V = co.reshape(-1, 3)[sample] @ Ms[:3, :3].T + Ms[:3, 3]
                d2 = ((V[:, None, :] - Gp[None]) ** 2).sum(2)
                idx = d2.argmin(1)
                sd = ((V - Gp[idx]) * Gn[idx]).sum(1)
                inpl = np.sqrt(np.maximum(d2[np.arange(len(V)), idx] - sd ** 2, 0.0))
                on = (inpl < spacing * 0.75) & not_thumb & (sd > -3.0 * cm)
                if not on.any():
                    break
                need = float((-CLEAR_CM * cm - sd[on]).min())       # move along the normal by at most this
                if need >= -1e-4:
                    break
                n_ = Gn[idx[on]].mean(0)
                n_ /= np.linalg.norm(n_) + 1e-12
                pose = [tuple(np.array(pose[0]) + n_ * (need - 0.02 * cm))] + list(pose[1:])
        finally:
            for m_ in mods:
                m_.show_viewport = True
        return pose

    # ---- each turn's window of frames and its clock (game seconds at every frame)
    plans = []
    for k, s, e, way in turns:
        kind = 'fwd' if way > 0 else 'back'
        T, t0 = D[kind], float(D[kind + '_t0'])
        a, b = (float(x) for x in D[kind + '_marks'])
        t_end = t0 + (len(T) - 1) / D['fps']
        release = e
        if way < 0:                                         # turning back: let go part way
            release = next((f for f in range(s, e + 1) if angle(k, f, way) >= math.radians(LET_GO_DEG)), e)
        b_rel = a + (b - a) * (release - s) / max(1, e - s)
        leave = max(t0, a - 0.55)                           # the game's hand leaves its rest about here...
        back = min(t_end, b_rel + (0.75 if way > 0 else 0.6))   # ...and is back resting about here
        plans.append(dict(k=k, s=s, e=e, way=way, kind=kind, T=T, t0=t0, a=a, b_rel=b_rel, release=release,
                          pre=(a - leave) * fps * SLOW, post=(back - b_rel) * fps * SLOW, leave=leave, back=back))
    for i in range(len(plans) - 1):                         # not enough time between two: both go quicker
        p, q = plans[i], plans[i + 1]
        room = q['s'] - p['release']
        need = p['post'] + q['pre']
        if need > room > 0:
            r = room / need
            p['post'] *= r
            q['pre'] *= r

    def clock(P, f):
        if f < P['s']:
            return P['a'] - (P['s'] - f) / P['pre'] * (P['a'] - P['leave']) if P['pre'] > 0 else P['a']
        if f <= P['release']:
            return P['a'] + (P['b_rel'] - P['a']) * (f - P['s']) / max(1, P['release'] - P['s'])
        return P['b_rel'] + (f - P['release']) / max(1e-6, P['post']) * (P['back'] - P['b_rel']) if P['post'] > 0 else P['back']

    out = [None] * n_frames
    phases = ['hold'] * n_frames
    grip_cache = {}
    for P in plans:
        k, s, way, T = P['k'], P['s'], P['way'], P['T']
        f0 = int(math.floor(s - P['pre']))
        f1 = int(math.ceil(P['release'] + P['post']))
        # taking hold: the edge grip at the captured spot where the page is first lifted
        row_a = _series(T, P['t0'], D['fps'], P['a'])
        up_a = float(np.clip(min(row_a[1], GRIP_UP), 0.06, 0.9))
        if (k, way) not in grip_cache:
            pt, fr = thing_at(k, s, 1.0, up_a)
            # (thumb on the page's front, fingers on its back: turning a page over that is thumb on
            #  top; turning one back - lying turned over on the left - fingers on top, thumb tucked under)
            grip_cache[(k, way)] = edge_grip(pt, fr)
        G0 = grip_cache[(k, way)]
        for f in range(max(0, f0), min(n_frames, f1 + 1)):
            t = clock(P, f)
            row = _series(T, P['t0'], D['fps'], t)
            pose = free_pose(f, row)
            # holding the page: the fingers on the app's own page edge, the captured height up it
            c = HS._smooth((t - (P['a'] - ON_S)) / ON_S) * (1 - HS._smooth((t - P['b_rel']) / ON_S))
            if c > 0 and s - 3 <= f <= P['release'] + 4:
                ff = min(max(f, s), P['release'])
                # (the grip stays low on the page all the way, as in the game: the recording's
                #  fingertips only seem to climb because a raised hand looks higher from the eyes)
                up_c = up_a
                # (while the page stands up the grip slides in towards the spine, so the hand stays at
                #  about half the page's width up - as in the game - instead of riding its far edge)
                along = 1.0 - EDGE_IN - (1.0 - STAND_ALONG) * math.sin(angle(k, ff, way))
                pt, fr = thing_at(k, ff, along, up_c)
                prog = HS._smooth((ff - s) / max(1, P['release'] - s))
                end_pose = rest_pose(min(n_frames - 1, P['release'] + 1)) if way < 0 else free_pose(ff, row)
                m = HS._slerp_m(HS._frame(G0[1], G0[2]), HS._frame(end_pose[1], end_pose[2]), prog)
                n = np.array(fr[2])
                hold = [tuple(np.array(pt) + n * 0.4 * cm), tuple(m.col[0]), tuple(m.col[1]), G0[3], 0.0]
                pose = mix(pose, hold, c)
                pose = keep_off(k, f, pose, way)                  # (also while taking hold and letting go)
                phases[f] = f'turn {k}'
            else:
                phases[f] = 'free'
            # resting whenever the game's hand is at its resting spot (it leaves and comes back smoothly)
            dist = float(np.hypot(row[0] - rest_uv[0], row[1] - rest_uv[1]))
            r = 1 - HS._smooth((dist - REST_NEAR[0]) / (REST_NEAR[1] - REST_NEAR[0]))
            if not (s <= f <= P['release']):
                r = max(r, 1 - HS._smooth((t - P['leave']) / REST_S) * (1 - HS._smooth((t - (P['back'] - REST_S)) / REST_S)))
            else:
                r *= 1 - c
            if r > 0:
                pose = mix(pose, rest_pose(f), r)
            out[f] = pose
    for f in range(n_frames):
        if out[f] is None:
            out[f] = list(rest_pose(f))
    HS.LAST_PHASES[:] = phases
    return HS._smooth_poses(out, HS.JOIN_SMOOTH_S * fps)
