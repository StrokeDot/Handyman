# Instructions for assistants working on MotionCraft

## HANDOFF.md is mandatory

1. **Before any work**, read `HANDOFF.md` (repo root). It holds the current state, decisions, open problems and
   next steps, so the whole chat history is not needed.
2. **After every change**, update `HANDOFF.md` in the same session. A change is any commit, push, release,
   Blender scene change, new decision or finding. Then do both:
   - commit and push it to `main` (a docs-only push does not publish a release; only an `APP_VERSION` bump does),
     and check on GitHub that the push landed;
   - write the same file locally to `C:\Users\Alejandro\AppData\Roaming\MotionCraft\HANDOFF.md`.
3. **When the owner gives a new task**, send them the current `HANDOFF.md` along with your reply.
4. Keep it under ~150 lines: replace outdated lines instead of appending history.

## Working rules

- Work on feature branches. Releases: bumping `APP_VERSION` in `version.py` on `main` publishes the installer
  (routine releases are pre-approved by the owner). `CHANGES.md` must stay cp1252-safe.
- Keep the hand prototype (`prototype/hand-page-turn`) isolated until it is validated; one targeted change at a time.
- Before saying an animation change is done, render the full animation as video, review every frame, and list
  the defects you found.
- Only one assistant at a time can be connected to Blender (MCP add-on on `localhost:9876`); do not edit the same
  scene at the same time as another assistant.
- Never ask the owner to paste passwords, tokens or keys into a chat.
