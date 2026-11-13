"""One page turned over and back, by hand, in an isolated scene - and measured.

    python3 turn_test.py base_job.json out_dir [--durations 0.5,1.0,2.0] [--style under|on] [--render]

base_job.json: any render job (blender_bridge.make_job) for the journal book; its book, size and
look are kept, its timeline replaced by: one page turned over, a pause, the same page turned back.

For every duration it reports (out_dir/report.json, and printed):
  slip_cm      how far the thumb and the finger move ALONG the page while they hold it (from the
               lift to the page standing up); 0 = they stay on the same spot of the paper
  thumb_cm / finger_cm   their distance from the paper while holding (thumb on the side it grips,
               + = on its own side, - = through the page)
  through      the most skin edges cutting through any page in one frame, and in how many frames
  lag          the holding error measured against the page one frame earlier / later divided by
               the error against the page at the same frame (> 1: the hand is in step with the page)
  scrub_diff   the largest difference in the hand's bones between playing the frames forwards and
               backwards (0 = every frame is the same whichever way you scrub)
With --render it also renders the key moments of both turns (forward and back) for each duration.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))

import bpy  # noqa: E402
import numpy as np  # noqa: E402

import hand_scene as H  # noqa: E402
import journal_geom as G  # noqa: E402
import journal_scene as JS  # noqa: E402


def make_job(base, duration, style, out_dir):
    job = dict(base)
    fps = int(job.get('fps') or 30)
    d = max(4, round(duration * fps))
    t0 = round(0.8 * fps)
    pause = round(max(1.2, duration) * fps)
    job['clip_list'] = [dict(kind='turn', start=t0, duration=d, smoothness=1.0),
                        dict(kind='turn_back', start=t0 + d + pause, duration=d, smoothness=1.0)]
    job['end_hold'] = 1.2
    job['hand'] = True
    job['hand_left'] = True
    job['hand_left_style'] = style
    job['turn_style'] = 'pushed'
    job['out_dir'] = out_dir
    job.pop('frames', None)
    job.pop('hand_bake_out', None)
    return job


def measure(job):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root, _, _, _, obs, strap = JS.build(job)
    sc = JS.job_scene(job)
    held = job.get('hand_left_style') == 'under'
    hand, plan, left, lplan = JS.make_hands(job, root, sc, len(obs), None, held)
    phases, keyinfo = list(H.LAST_PHASES), dict(H.KEY_DEBUG)
    cm = 1.0 / hand.pw
    inv = root.matrix_world.inverted()
    pb = hand.rig.pose.bones
    n_sh = len(obs)

    def page_state(f):
        prog = sc.evaluate(f)['sheet_progress']
        ts = [float(prog[k]) if k < len(prog) else 0.0 for k in range(n_sh)]
        G.set_turned(ts)
        return ts, G.curve_weights(ts)

    def tips(f):
        hand.apply(plan[f])
        bpy.context.view_layer.update()
        M = inv @ hand.rig.matrix_world
        return np.array((M @ pb['thumb_03_r'].tail)[:]), np.array((M @ pb['index_03_r'].tail)[:])

    # ---- holding: slip along the page, distance from it, and being in step with it
    res = {}
    for way in (1, -1):
        carry = sorted(f for f, v in keyinfo.items() if v[4] == way and v[0] in ('lift', 'upright')
                       and (v[0] == 'lift' or v[2] < 0.02) and phases[f].startswith('turn'))
        carry = [f for f in carry if keyinfo[f][3] >= H.KEY_LIFT_DEG - 1e-6 and keyinfo[f][3] <= 90.0]
        if not carry:
            res['forward' if way > 0 else 'back'] = None
            continue
        k = int(phases[carry[0]].split()[1])
        contact = (1.0 - (H.KEY_CONTACT_IN_CM if way > 0 else H.KEY_BACK_CONTACT_IN_CM) * cm, H.KEY_CONTACT_UP)
        loc_t, loc_i, sd_t, sd_i, lagr = [], [], [], [], []
        for f in carry:
            th, ix = tips(f)

            def local(g):
                ts, cw = page_state(g)
                p, fr = hand.page_at(k, ts[k], cw[k], *contact)
                F = np.stack([np.array(fr[0]), np.array(fr[1]), np.array(fr[2]) * way], 1)
                return F.T @ (th - np.array(p)), F.T @ (ix - np.array(p))
            lt, li = local(f)
            loc_t.append(lt)
            loc_i.append(li)
            sd_t.append(lt[2] / cm)
            sd_i.append(li[2] / cm)
            if 0 < f < sc.frames - 1:
                e0 = np.linalg.norm(lt[:2] - loc_t[0][:2])
                ep = min(np.linalg.norm(local(f - 1)[0][:2] - loc_t[0][:2]),
                         np.linalg.norm(local(f + 1)[0][:2] - loc_t[0][:2]))
                if e0 > 1e-6:
                    lagr.append(ep / e0)
        lt = np.array(loc_t)[:, :2]
        li = np.array(loc_i)[:, :2]
        slip = max(np.linalg.norm(lt - lt[0], axis=1).max(), np.linalg.norm(li - li[0], axis=1).max()) / cm
        res['forward' if way > 0 else 'back'] = dict(
            frames=[carry[0], carry[-1]], slip_cm=round(float(slip), 2),
            thumb_cm=[round(float(min(sd_t)), 2), round(float(max(sd_t)), 2)],
            finger_cm=[round(float(min(sd_i)), 2), round(float(max(sd_i)), 2)],
            lag=round(float(np.median(lagr)), 2) if lagr else None)
    # ---- cutting through pages, over the whole animation
    skin = next(o for o in hand.objects if o.type == 'MESH' and not o.name.startswith('Sleeve'))
    for m in skin.modifiers:
        if m.type == 'SUBSURF':
            m.show_viewport = False
    E = np.array([e.vertices[:] for e in skin.data.edges])
    A, U = 40, 56
    interior = np.array([(0 < i < A - 1 and 0 < j < U - 1) for i in range(A) for j in range(U)])
    from scipy.spatial import cKDTree
    worst, bad, where_bad = 0, 0, []
    for f in range(sc.frames):
        ts, cw = page_state(f)
        turned = sum(1 for t in ts if t >= 0.5)
        ks = {k for k, t in enumerate(ts) if 0.0 < t < 1.0} | {max(0, turned - 1), min(n_sh - 1, turned)}
        hand.apply(plan[f])
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        ev = skin.evaluated_get(dg)
        me = ev.to_mesh()
        Mw = np.array(inv @ skin.matrix_world)
        V = np.array([v.co[:] for v in me.vertices]) @ Mw[:3, :3].T + Mw[:3, 3]
        ev.to_mesh_clear()
        n_cross = 0
        for k in ks:
            g = G.sheet_state(k, ts[k], cw[k])
            P = np.zeros((A * U, 3))
            N = np.zeros((A * U, 3))
            for i in range(A):
                for j in range(U):
                    pt, fr = H._surface(g, i / (A - 1), j / (U - 1))
                    P[i * U + j], N[i * U + j] = pt, fr[2]
            d, idx = cKDTree(P).query(V)
            sd = ((V - P[idx]) * N[idx]).sum(1)
            inpl = np.sqrt(np.maximum(d ** 2 - sd ** 2, 0)) / cm
            ok = interior[idx] & (inpl < 0.5) & (np.abs(sd) / cm < 1.5)
            a, b = E[:, 0], E[:, 1]
            n_cross = max(n_cross, int((ok[a] & ok[b] & (np.sign(sd[a]) != np.sign(sd[b]))).sum()))
        worst = max(worst, n_cross)
        bad += n_cross > 6
        if n_cross > 6:
            where_bad.append((f, phases[f], n_cross))
    res['through'] = dict(worst_edges=worst, frames_over_6_edges=bad, frames=sc.frames, where=where_bad[:40])
    # ---- scrubbing: the same pose whichever way the frames are played
    def bones(f):
        hand.apply(plan[f])
        bpy.context.view_layer.update()
        return np.array([np.array(b.matrix) for b in pb])
    fwd = {f: bones(f) for f in range(0, sc.frames, 3)}
    diff = max(float(np.abs(bones(f) - fwd[f]).max()) for f in sorted(fwd, reverse=True))
    res['scrub_diff'] = round(diff, 8)
    return res, sc, keyinfo


WANT = (0.0, 25.0, 60.0, 90.0, 118.0, 145.0, 179.0)


def render(job, keyinfo, out_dir):
    picks = []
    for way in (1, -1):
        for want in WANT:
            fs = [f for f, v in keyinfo.items() if v[4] == way]
            if fs:
                picks.append(min(fs, key=lambda f: abs(keyinfo[f][3] - want)))
    job = dict(job, frames=sorted(set(picks)), width=640, height=400, samples=16)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'job.json')
    with open(path, 'w') as fh:
        json.dump(job, fh)
    sys.argv = ['x', '--', path]
    JS.main()
    return sorted(set(picks))


def main():
    args = [a for a in sys.argv[1:] if a != '--']
    base = json.load(open(args[0]))
    out = args[1]
    durations = [0.5, 1.0, 2.0]
    style = 'under'
    if '--durations' in args:
        durations = [float(x) for x in args[args.index('--durations') + 1].split(',')]
    if '--style' in args:
        style = args[args.index('--style') + 1]
    os.makedirs(out, exist_ok=True)
    report = {}
    for d in durations:
        sub = os.path.join(out, f'turn_{d:.2f}s')
        job = make_job(base, d, style, sub)
        if '--quick' in args:                           # (only the key moments rendered, nothing measured)
            bpy.ops.wm.read_factory_settings(use_empty=True)
            root, _, _, _, obs, strap = JS.build(job)
            sc = JS.job_scene(job)
            JS.make_hands(job, root, sc, len(obs), None, style == 'under')
            res, keyinfo = {}, dict(H.KEY_DEBUG)
        else:
            res, sc, keyinfo = measure(job)
        report[f'{d:.2f}s'] = res
        print(f'TURN {d:.2f}s', json.dumps(res), flush=True)
        if '--render' in args:
            frames = render(job, keyinfo, sub)
            report[f'{d:.2f}s']['rendered_frames'] = frames
    with open(os.path.join(out, 'report.json'), 'w') as fh:
        json.dump(report, fh, indent=1)


if __name__ == '__main__':
    main()
