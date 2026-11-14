"""Forearm twist bones (step 6): a real forearm turns gradually - hardly at the elbow, fully at
the wrist - so the skin and sleeve twist evenly instead of wringing at one spot. This adds two
twist bones along the forearm (at a third and two thirds of its length) and spreads the
forearm's skin and sleeve weights over lowerarm_r -> twist_01 -> twist_02 by how far along the
forearm each point is. hand_scene.Hand.apply() turns them by part of the hand's roll.

    python3 twist_bones.py resources/hand/hand.blend
"""
import sys

import bpy
from mathutils import Vector

TWISTS = (('lowerarm_twist_01_r', 1 / 3), ('lowerarm_twist_02_r', 2 / 3))


def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def main():
    args = [a for a in sys.argv[1:] if a != '--']
    blend = args[0]
    bpy.ops.wm.open_mainfile(filepath=blend)
    rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = rig
    for o in bpy.context.view_layer.objects:
        o.select_set(o is rig)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    lo = eb['lowerarm_r']
    elbow, wrist = lo.head.copy(), eb['hand_r'].head.copy()
    for name, at in TWISTS:
        if name in eb:
            eb.remove(eb[name])
    for name, at in TWISTS:
        b = eb.new(name)
        b.head = elbow.lerp(wrist, at)
        b.tail = elbow.lerp(wrist, at + 1 / 3)
        b.roll = lo.roll
        b.parent = lo
        b.use_connect = False
        b.use_deform = True
    bpy.ops.object.mode_set(mode='OBJECT')
    # (in the armature's own space)
    axis = wrist - elbow
    length = axis.length
    axis.normalize()
    names = ['lowerarm_r'] + [n for n, _ in TWISTS]
    centres = [0.0, 1 / 3, 2 / 3]
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or 'lowerarm_r' not in ob.vertex_groups:
            continue
        to_rig = rig.matrix_world.inverted() @ ob.matrix_world
        groups = {n: (ob.vertex_groups[n] if n in ob.vertex_groups else ob.vertex_groups.new(name=n)) for n in names}
        g_lo = groups['lowerarm_r'].index
        moved = 0
        for v in ob.data.vertices:
            w = next((g.weight for g in v.groups if g.group == g_lo), 0.0)
            if w <= 0.0:
                continue
            t = (to_rig @ v.co - elbow).dot(axis) / length          # 0 elbow .. 1 wrist
            # share of the forearm's weight per bone: a smooth hat around each bone's place
            shares = [max(0.0, 1.0 - abs(t - c) * 3.0) for c in centres]
            if t >= centres[-1]:
                shares = [0.0, 0.0, 1.0]
            elif t <= 0.0:
                shares = [1.0, 0.0, 0.0]
            tot = sum(shares) or 1.0
            for n, s in zip(names, shares):
                if s > 1e-4:
                    groups[n].add([v.index], w * s / tot, 'REPLACE')
                elif n != 'lowerarm_r':
                    groups[n].remove([v.index]) if any(g.group == groups[n].index for g in v.groups) else None
            if shares[0] / tot < 1e-4:
                groups['lowerarm_r'].remove([v.index])
            moved += 1
        print(ob.name, 'forearm points spread over the twist bones:', moved)
    bpy.ops.wm.save_mainfile(filepath=blend)
    print('bones', [b.name for b in rig.data.bones])


if __name__ == '__main__':
    main()
