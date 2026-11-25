# MotionCraft — Handoff (2026-11-25)

> Assistants: read this first, then keep it current. Update it at the end of each work session and push it.

MotionCraft (repo `StrokeDot/Handyman`, formerly Handyman) is a Windows app (Python + PySide6) that drives
Blender to render book page-turn animations from user-designed book templates. The current goal is a
hand and arm turning the pages with Red Dead Redemption 2 (Arthur Morgan journal) quality.
Owner: Alejandro (non-technical, right-handed, uses voice-to-text).

## Current state

**App (main branch): v0.31.0, released 2026-11-20.**
- 0.31.0 (pushed by another assistant): "cinematic" book opening — tilt, cover peel, hands-free page curls.
  Standard cover lift stays the default.
- 0.30.2: Blender 5.3 support, a Blender version picker in Settings, and an automatic retry with the next
  installed Blender (5.3 → 5.2) if a render or hand bake fails. Also fixed copied books losing their paper
  texture, and made the CI test renders fail when a render fails.
- 0.30.0–0.30.1: hand motion driven by RDR2 video capture (`hand_capture.py` + `resources/hand/rdr2_turns.npz`).
  The right arm comes in from the lower right.
- The hand animation in the shipping app is still not good enough: wrist bends, arm placement, and the page
  passing through the hand.

**Isolated prototype (branch `prototype/hand-page-turn`, tip `d043adc`).**
- `tools/hand/prototype/`: `proto_scene.py` (hand, sleeve and one page; IK targets; one progress parameter;
  automated checks), `DIAGNOSIS.md`, `SCENE_STATE.md`.
- Best automated result: wrist bend 24° median / 53° max, but page crossings remain.

**Motion capture from the user's own recording (2026-11-18). These files are NOT in git.**
- Source: `%APPDATA%\MotionCraft\capture\Camera Motion.mp4`, three angles one after another:
  - top-down: 0:00–1:11, moving head camera;
  - side: 1:11–2:26, fixed;
  - front: 2:26–end, fixed.
- The angles are synced to within a frame (checked on an open-palms / fists gesture).
- Only the top-down view was usable:
  - The book is an A5 ring binder (14.8 × 21 cm per page), the same size as the prototype page.
  - Real turn: grip a third of the way up the right edge with the wrist below the book; the page goes over in
    about 0.8 s; the hand returns low along the bottom in about 1.1 s.
- Blender files in `%APPDATA%\MotionCraft\proto\`:
  - `capture_turn_test.blend` = `capture_turn_good.blend`: smooth version. Max wrist jerk 7 mm/frame², hand
    turn ≤ 3°/frame, wrist bend ≤ 65°. Page crossing mid-turn: 72 skin points at worst.
  - `capture_turn_rest.blend`: adds a 2 cm book block and a resting pose with the thumb on the page.
  - `capture_turn_lowarm.blend`: shoulder moved below the book; resting grip looks like the RDR2 reference
    (palm up under the book, thumb over the edge).
  - `capture_turn_solver.blend`: hold-solver experiment. Half the crossings, but jerky (16°/frame) and wrist
    up to 101°. Rejected.
- Scripts and data that survive (in `/mnt/user-data/outputs/` and on the PC in `proto\`):
  `capture_turn*.json`, `hold_solver2.py`, `rest_grip3–7.py`.
- Lost when the work container was replaced (never pushed):
  - the video-analysis scripts: `pagequad.py`, `smoothquad.py`, `onpage.py`, `build_turn.py`,
    `clean_turn*.py`, `obs.py`, `sync.py`;
  - the `tools/hand/mocap3/README.md` notes.
- Full-frame review of `capture_turn_lowarm.blend` (`proto\out_cap\lowarm_review.mp4`):
  - good: only the rests (frames 0–19 and 112–132);
  - frames 20–24: the hand flips out from under the book;
  - from frame 24: the page lifts by itself;
  - frames 34–63: the arm locks straight across the book;
  - frames 96–111: the hand twists back into the rest pose.

## Tools on the user's PC

- **Blender:** 5.3 at `C:\Program Files\Blender Foundation\Blender 5.3\`. 5.2 and 4.4 are also installed.
- **Blender MCP:** the official Blender Lab "MCP" add-on 1.0.3, installed from the `https://lab.blender.org/`
  extension repository. It auto-starts on `localhost:9876` and serves **one client at a time**.
  - Claude desktop config: `%LOCALAPPDATA%\Claude-Data\claude_pzs8sxrjxfjjc\claude_desktop_config.json`.
    The server runs as `uvx --from git+https://projects.blender.org/lab/blender_mcp.git#subdirectory=mcp blender-mcp`.
  - Codex config: `C:\Users\Alejandro\.codex\config.toml`, section `[mcp_servers.blender]`.
    A backup is saved as `config.toml.before-blender`.
  - uv lives in `C:\Users\Alejandro\.local\bin`.
- **RGB MoCap** (github.com/toyxyz/toyxyz_RGBMocap) at `D:\RGBMocap\toyxyz_RGBMocap`:
  - `install.cmd` completed; start the app with `RGBMoCap.cmd`.
  - Models still missing:
    - SMPL-X v1.1 neutral: needs registration;
    - MANO `MANO_RIGHT.pkl`: use the **mirror** link on mano.is.tue.mpg.de/download.php, because the main link
      returns 403;
    - SAM 3D Body: gated on Hugging Face; access requested?
  - Plan: run **GVHMR** (+ the HandFlow add-on), which needs only SMPL-X and MANO, while SAM 3D Body (needed
    for ExMR) waits for approval.
- **Hardware:** RTX 4070 Super, 12 GB VRAM.

## Decisions made

- **Release flow:** a push to `main` that bumps `APP_VERSION` in `version.py` publishes the installer, and the
  in-app updater picks it up.
  - Do the work on feature branches.
  - Routine releases are pre-approved by the owner.
  - `CHANGES.md` must stay cp1252-safe.
- **GitHub:** use the REST API through `gh api`; GraphQL is blocked in this environment.
- **Hand prototype:** keep it isolated. Do not change the shipping hand code until the prototype is validated.
  One targeted change at a time.
- **Definition of done:** render the full animation as video, review every frame, and list the defects
  **before** reporting. Numbers plus a few stills missed visible problems.
- **Animation method:** stop automatic per-frame fixing; it kept fixing one thing and breaking another.
  Recommended next method: key poses approved one at a time, then locked; the capture supplies timing.
- **Arm placement:** in RDR2 the book is held up and the forearm comes from below. A shoulder above the book
  (book on a table) forces twisted hands.
- **Mocap add-ons:** BlendCap ($60) and RGB MoCap (free) give the whole arm. Neither handles hand–page
  contact, which stays a manual or key-pose job. The owner chose to test RGB MoCap first.
- **Credits:** JUST (@teenjust500), CC BY 4.0, for the hand asset.

## Open problems

1. The arm (shoulder, elbow, forearm twist) is placed by a fixed rule, not solved or captured. This is the root
   cause of wrist bends, the out-of-reach carry and the flips.
2. Mid-turn (page at about 70–140°), the page passes through the thumb and fingers.
3. Reach: holding the corner at full page width is too far for a low shoulder. Letting the grip slide toward
   the spine as the page stands up (the prototype's `STAND_ALONG`) should fix it.
4. The turn does not start from the resting grip (thumb on top, fingers under), so the hand flips at the grab.
5. The release and the return are hand-authored curves, not captured.
6. Some capture scripts were lost (see above). Rebuild them only if the top-down capture is reused.
7. `device_commit_files` can serve an old copy under the same name. Send changed scripts under a new name.

## Next steps

1. Finish the RGB MoCap model setup: SMPL-X, MANO (mirror link), then GVHMR.
2. Reconstruct the front clip (2:26–end, Static Camera, Foot correction off). Export the Blender project into
   `D:\RGBMocap\toyxyz_RGBMocap\` (this session has read/write access there).
3. Import it into Blender 5.3 over MCP and retarget the arm to `HandRig`. Compare shoulder, elbow and wrist
   with the video frame by frame.
4. Build the turn from key poses, each approved by the owner and locked:
   rest grip → little grab → lift → page standing → release → back to rest.
   Use the captured arm where it helps.
5. After every change, render the full video, review every frame, then report.
6. Only when the prototype is validated, port it into the app (`hand_scene.py` / `hand_capture.py`) and release.
7. Commit the surviving scripts to `prototype/hand-page-turn`, and check that the push lands on GitHub.

## Key files

**App (main):**
- `app.py`: UI and render workers; the Blender fallback is in `_on_failed` / `_hands_failed`.
- `blender_bridge.py`: `find_blenders`, `fallback_blender`, `version_from_path`, job building.
- `journal_scene.py`, `book_scene.py`, `page_curl.py`, `scene.py`: Blender scene scripts.
- `hand_scene.py`, `hand_capture.py`, `hand_bake.py`, `resources/hand/`: the shipping hand.
- `templates.py`: books; texture fallback to `resources/templates/`.
- `tools/ci_preview.py`, `.github/workflows/preview.yml`: CI test renders.
- `.github/workflows/release.yml`: build and publish.

**Prototype branch:**
- `tools/hand/prototype/*`
- `tools/hand/rdr2_capture/*`: RDR2 video capture tools.

**On the PC:**
- `%APPDATA%\MotionCraft\proto\`: `capture_turn_*.blend`, `capture_turn*.json`, `hold_solver2.py`,
  `rest_grip*.py`, `out_cap\`.
- `%APPDATA%\MotionCraft\capture\`: `Camera Motion.mp4`, `Turning PagesLight.mp4` (RDR2 reference).
