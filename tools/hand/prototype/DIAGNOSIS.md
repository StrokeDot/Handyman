# Phase 1 - Diagnosis of the hand, sleeve and page interaction (2026-11-14)

Scope: the right hand, wrist and sleeve, and how they touch the page. The book is accepted as is.
Evidence: `resources/hand/hand.blend` inspected (`diag_inspect` numbers below), the arm posed alone
and rendered (`diag_poses.py`), and the app's own motion (0.30.1) measured frame by frame.

## Verdict per possible cause

| Cause | Finding | Severity |
|---|---|---|
| Mesh geometry / proportions | Clean artist meshes: hand 2,833 vertices (glove), sleeve 2,143 (artist's sleeve). Bone lengths: upper arm 26.4 cm, forearm 20.1 cm, hand length ~19 cm - plausible (forearm a little short). No defect. | none |
| Bone placement / skin weights | All vertices weighted (no strays). Hand weights sum 0.85-1.31 per vertex, but both Blender and the live view normalise them (hand_bake keeps the top 4, normalised). Wrist/cuff hold their shape through wrist bends and forearm twists up to ~70 deg. | minor |
| Sleeve deformation | No corrective shape keys at all. Bending the elbow 45-90 deg creases and pinches the inside of the sleeve (plain linear blend skinning). The elbow is mostly out of the first-person view, so this is secondary; the cuff is fine. | medium |
| IK / parenting | No Blender constraints: the arm is posed by our own two-bone IK in Python (hand_scene.Hand._ik), the hand's orientation chosen FIRST (to fit the page) and the arm made to follow from a fixed shoulder. Result measured on the app's motion: **the wrist is bent ~44 deg from the forearm's line even at rest, up to 75 deg** (a relaxed real wrist: 10-20 deg). The hand and forearm do not line up - the arm looks broken at the wrist. Twist is now within a real forearm's range (-45..+9 deg), no jumps. | **main defect** |
| Hand / page synchronisation | Contact is computed from the page's own frame each frame, so the grip follows the page; page crossings at most ~35 skin edges per frame; same result scrubbing backwards. But the page is rigid while held - it does not bend under the fingers - so the contact reads as a hand beside a board. | medium |
| Camera / lighting | Our first-person framing shows the whole book small; RDR2's camera is much closer (book overflowing the screen) and centred right of the spine, so the hand is big and the arm enters from the lower right corner. Flat live-view lighting vs. game daylight. | medium (presentation) |

## Root causes to address in the prototype
1. Pose selection order: choose the hand pose with the wrist kept near the forearm's line (soft limit
   ~25 deg), the arm entering from the lower right; contact is then reached by moving the arm (IK
   target) - not by bending the wrist.
2. Contact as a constraint relative to the page (pinch point on the page at a fixed spot of the page),
   checked for slip and penetration.
3. Corrective shapes for the sleeve at the elbow and cuff (driven by elbow angle / wrist bend).
4. One progress parameter (0..1) driving the whole turn, so scrubbing either way is identical.
