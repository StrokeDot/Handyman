# Capturing the page-turn motion from a video (development tools, not part of the app)

How `resources/hand/rdr2_turns.npz` was made from a 1440p recording of Red Dead Redemption 2's journal
(the menu hidden, bright daylight, many forward turns and turns back). Run in this order, in a folder
holding the video as `clip.mp4` (needs `pip install mediapipe opencv-python scipy` and MediaPipe's
`hand_landmarker.task`, path in `HAND_MODEL`):

1. `trackimg.py clip.mp4 trk_plain.npz 30 1280` and again with `",eq=contrast=1.2:gamma=1.2"` as a
   fifth argument into `trk_bright.npz` - the hand's 21 points in every frame (MediaPipe, per image).
2. `bookquad.py clip.mp4 quads.npz` - the open spread's outline per frame: pale pages against the
   background, each edge a robust line fit, the left edge mirrored from the right about the spine
   (it is often off the picture). Then smooth it over time (a 1 s running median; see the notes in
   the session) into `quads_smooth.npy`.
3. `handbook.py` - the hand on the book (u: -1 left edge, 0 spine, 1 right edge; v: 0 bottom, 1 top).
4. `features.py`, `templates.py` - every turn found, all repeats of each kind aligned in time and
   averaged (they fill each other's gaps), the resting spot measured.

What is used: where the thumb and index fingertips are on the spread over time, and the timing.
What is not: the tracker's depth and the hand's pointing direction off the page (unreliable on game
footage), and the finger bends (too noisy) - `hand_capture.py` sets those per phase.
A raised hand looks higher up the page from the player's eyes: the fingertips' apparent climb during
a turn is height, not a grip moving up the page (`hand_capture.GRIP_UP` keeps the grip low).
The same steps work on a video of a real hand turning pages (filmed from the eyes, bare hand).
