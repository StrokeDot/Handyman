# Prototype scene state (persistent notes) - updated 2026-11-14

Run: `python3 tools/hand/prototype/proto_scene.py -- out_dir [--save scene.blend]` (Blender's bpy
module; ~15 s). Writes `fp_000..100.png` (first person), `close_000..100.png` (fingertips and cuff,
50 mm), and `checks.json` (61 samples of p + summary). Nothing in the app is touched.

## Scene structure (object names)
- `HandRig` (armature, from resources/hand/hand.blend, real size, placed with `upperarm_r` at SHOULDER)
  - `Hand` (glove mesh), `Sleeve` (sleeve mesh): armature-skinned, unchanged artist assets.
  - constraints: `lowerarm_r` IK (target `WristTarget`, pole `ElbowPole`, chain 2, pole angle -90),
    `hand_r` Copy Rotation (target `HandAim`, world space).
  - fingers: rotations from the rig's own `motioncraft_hand` data (relaxed -> pinch, FINGERS_HOLD).
- `Page` (24 x 16 grid, rewritten per p from `page_point`): hinged at the spine (x = 0), turning with
  a lag towards its free edge (LAG); `LeftPage`, `UnderPage`: flat context planes.
- `Camera`: moved per render (first person; close-up at the pinch).

## The single parameter p (0..1) of a forward turn (`phase`, `target`)
0-0.12 reach from resting (REST on the page edge) to the grip (GRIP); 0.12-0.84 the page turns to
177 deg; the pinch held on the page at (along, GRIP up), along sliding from 0.95 to STAND_ALONG as the
page stands (the arm cannot reach the far edge high up, and the game's hand stays low); 0.78-0.90
let go; 0.88-1 back to resting.

## How the hand's rotation is chosen (`Arm.candidates`, `solve`)
Candidates: thumb->index line through the page, slanted up to MAX_SLANT (15 deg steps, 30 deg azimuth),
turned about itself (15 deg). Cost: wrist bend over WRIST_SOFT (x3) + bend (x0.2) + slant + back of the
hand away from the eyes (x120 below 0.25) + points of the hand crossing the page (x1.5, while holding).
Dynamic programming over the 70 best per step (61 steps), turn per step > 9 deg penalised, then a
gaussian over the path. Pose at any p = slerp between steps -> identical whichever way it is played.

## Findings so far
- Root cause of the bent wrist: the rig's half-closed pinch has its thumb->index line only 38 deg from
  the hand's pointing direction; demanding it straight through the page forces the hand to point into
  the page (90-115 deg bends). Slanting the grip fixes most of it (median 112 -> ~40 deg).
- IK reaches every target exactly (0.0 mm) as long as the target is within reach; the far edge of a
  standing page is not (hence the sliding grip).

## Current results (run5)
contact error max 2.1 mm | wrist bend median 40, max 90 (p 0.25-0.35) | hand turn per step max 18.8 deg |
points crossing the page max 181 (p 0.25-0.35; ~40 elsewhere) | scrub difference 0.0
Open: the lift (p 0.25-0.35); the resting grip's 49 deg wrist; sleeve corrective shapes (elbow pinch);
render the checkpoints in EEVEE/4K once the motion passes.
