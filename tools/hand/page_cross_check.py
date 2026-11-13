import sys, itertools
job_path = sys.argv[1]
sys.argv = ['x', job_path, '/tmp/none']
src = open('/tmp/claude-0/-home-claude/f14bba42-bd38-51ac-9134-8c5464a1a754/scratchpad/handtest/keyposes.py').read()
src = src.split('_probe()\n')[0] + '''
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
root, _, _, _, obs, strap = JS.build(job)
sc = JS.job_scene(job)
hand, plan_, left, lp = JS.make_hands(job, root, sc, len(obs), None, job.get('hand_left_style') == 'under')
import journal_geom as G
import os
f = FRAMES[os.environ['KEY']]
prog = sc.evaluate(f)['sheet_progress']
tsl = [float(prog[k]) if k < len(prog) else 0.0 for k in range(len(obs))]
G.set_turned(tsl); cw = G.curve_weights(tsl)
g = G.sheet_state(0, tsl[0], cw[0])
cm = 1.0 / hand.pw
A, U = 50, 70
pts = np.zeros((A, U, 3)); nrm = np.zeros((A, U, 3))
for i in range(A):
    for j in range(U):
        pt, fr = H._surface(g, i / (A - 1), j / (U - 1)); pts[i, j] = pt; nrm[i, j] = fr[2]
P2, N2 = pts.reshape(-1, 3), nrm.reshape(-1, 3)
interior = np.array([(0 < i < A - 1 and 0 < j < U - 1) for i in range(A) for j in range(U)])
skin = next(o for o in hand.objects if o.type == 'MESH' and not o.name.startswith('Sleeve'))
for m in skin.modifiers:
    if m.type == 'SUBSURF': m.show_viewport = False
names = {gg.index: gg.name for gg in skin.vertex_groups}
parts = []
for v in skin.data.vertices:
    grp = max(v.groups, key=lambda x: x.weight).group if v.groups else -1
    b = names.get(grp, '?'); parts.append('t' if b.startswith(('thumb_02', 'thumb_03')) else ('b' if b.startswith('thumb') else ('f' if b.split('_')[0] in ('index','middle','ring','pinky') else 'p')))
parts = np.array(parts)
inv = root.matrix_world.inverted()
ts0 = sc.evaluate(f)
def evaluate(pose):
    hand.apply(pose); bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get(); ev = skin.evaluated_get(dg); me = ev.to_mesh()
    M = np.array(inv @ skin.matrix_world)
    V = np.array([v.co[:] for v in me.vertices]); V = V @ M[:3, :3].T + M[:3, 3]
    ev.to_mesh_clear()
    from scipy.spatial import cKDTree
    d, idx = cKDTree(P2).query(V)
    sd = ((V - P2[idx]) * N2[idx]).sum(1) / cm
    inplane = np.sqrt(np.maximum(d ** 2 - (sd * cm) ** 2, 0)) / cm
    ok = interior[idx] & (inplane < 0.4) & (np.abs(sd) < 3)
    global ALL; ALL = {k: (round(float(sd[ok & (parts == k)].min()), 2), round(float(sd[ok & (parts == k)].max()), 2), int((ok & (parts == k)).sum())) for k in 'tbfp' if (ok & (parts == k)).any()}
    t = sd[ok & (parts == 't')]; fi = sd[ok & ((parts == 'f') | (parts == 'p'))]; tb = sd[ok & (parts == 'b')]
    ff = sd[ok & (parts == 'f')]; pp = sd[ok & (parts == 'p')]
    global FP; FP = (round(ff.max(), 2) if len(ff) else None, round(pp.max(), 2) if len(pp) else None, int((ok & (parts == 'p')).sum()))
    global LAST; LAST = (len(tb), (tb.min() if len(tb) else 0), (tb.max() if len(tb) else 0))
    return (t.min() if len(t) else 9.0), (fi.max() if len(fi) else -9.0)
evaluate(plan_[f])
print('ALL', os.environ['KEY'], ALL, flush=True)
'''
exec(compile(src, 'kp', 'exec'))
