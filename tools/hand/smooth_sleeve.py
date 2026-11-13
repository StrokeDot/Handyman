"""Calm the sleeve's draped cloth (step 5): the drape left small random lumps all over it, which
read as a crumpled sack rather than a coat sleeve. A gentle smoothing of its rest shape keeps the
big folds and removes the lumps (for the render and the live view alike).

    python3 smooth_sleeve.py resources/hand/hand.blend [iterations] [factor]
"""
import sys

import bpy

args = [a for a in sys.argv[1:] if a != '--']
blend = args[0]
iters = int(args[1]) if len(args) > 1 else 6
factor = float(args[2]) if len(args) > 2 else 0.5
bpy.ops.wm.open_mainfile(filepath=blend)
ob = bpy.data.objects['Sleeve']
old = ob.modifiers.get('Calm')
if old:
    ob.modifiers.remove(old)
m = ob.modifiers.new('Calm', 'SMOOTH')
m.factor, m.iterations = factor, iters
bpy.context.view_layer.objects.active = ob
while ob.modifiers[0].name != 'Calm':                 # first: smooth the rest shape, then bend it
    bpy.ops.object.modifier_move_up(modifier='Calm')
print('sleeve modifiers', [x.name for x in ob.modifiers])
bpy.ops.wm.save_mainfile(filepath=blend)
