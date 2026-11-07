# Handyman Foundation Hardening — Design Specification

**Status:** Design approved in conversation on 2026-10-18; this written specification and implementation plan are proposed for review. No application behavior is changed by this document.
**Repository:** StrokeDot/Handyman
**Baseline:** main @ 01ce147e03a8d6b4cce0935a138f4ddaf5c44eaa (Handyman 0.5.0)
**Approach:** Incremental, test-first, reviewable changes; no rewrite.

## 1. Purpose and success criteria

Preserve the working Windows 3D book/page-turn application while removing data-loss, process-lifecycle, export, release, and update risks. Prepare only the minimum shared boundaries needed to add another animation type later. Users must not lose existing projects or custom book templates as a result of hardening.

Success means:
- Existing .hmproj files, settings, and custom book templates remain readable.
- Missing images never silently change page indices or destroy paths on subsequent save.
- Failed, cancelled, or interrupted work leaves recoverable state; no surviving child processes or destroyed-running-thread crash.
- Alpha export smoke tests check real output, and a Windows Filmora overlay acceptance test is recorded separately.
- Pull requests run required tests, and releases do not publish merely because packaging produced an EXE.
- Updates use explicitly verified integrity data and preserve the last installed copy on failure.
- Book animation behavior is regression-tested before and after small, interface-preserving refactors.

## 2. Baseline architecture

- UI: PySide6 in app.py; live preview: live_view.py (PyOpenGL); outline: framing_view.py.
- Shared calculations: page_curl.py, book_model.py, camera_fit.py.
- Renderer: blender_bridge.py constructs jobs; book_scene.py executes jobs in Blender; encode.py runs FFmpeg.
- Project JSON: .hmproj currently serialized in app.py; custom templates: templates.py under %APPDATA%/Handyman/books.
- Distribution: installer/handyman.iss; .github/workflows/release.yml and preview.yml; updater.py.
- Existing checks: test_curl.py, test_camera.py, test_model.py, test_scene_mock.py, test_app_smoke.py, test_support.py, and CI render sampling.

Do not change geometry, camera conventions, timings, dimensions, Blender job schema, or the published v0.5.0 installer as a side effect.

## 3. Global invariants

1. Target Windows x64 with the current Python 3.12 / PySide6 / NumPy / PyOpenGL / Blender / FFmpeg setup; no framework migration.
2. No hardening change is made directly to main. Use isolated feature branches, a passing test-first red/green cycle, review, and an individually mergeable PR per phase.
3. No new animation types, model downloads, embedded Blender, mandatory cloud services, or database migration.
4. Never delete or silently rewrite user-controlled source images, .hmproj files, custom books, or incomplete render frames.
5. An error is surfaced explicitly; neither missing input nor rendering/encoding failure may be reported as success.
6. Existing v0.5.0 projects and settings remain readable. New fields have defaults and do not break older clients unnecessarily.
7. Required automated gates fail closed. Hardware/editor-specific acceptance tests are documented as manual gates, not falsely marked automated.
8. Nothing publishes a user-facing release until Windows acceptance is complete, including a Filmora alpha check.

## 4. Phase 1 — Project and template integrity

### Project storage contract

Introduce a pure-Python project_store.py with:
- load_project(path: Path) -> dict: validate the JSON top-level object and expected known fields; accept legacy unversioned objects and a schema_version of 1; reject unsupported future versions without mutating current UI state.
- save_project(path: Path, state: dict) -> None: write UTF-8 JSON to a temporary sibling, flush, then os.replace; preserve existing project as a recoverable .bak before replacement; clean temporary files on error.
- prepare_project_state(state: dict, project_path: Path) -> dict and resolve_project_state(state: dict, project_path: Path) -> dict: represent new page references as project-relative paths when possible, retain absolute paths otherwise, and resolve without reordering on open. Never automatically package or move referenced media.

The UI keeps the existing page ordering and a placeholder for each absent file. A missing page displays an explicit warning with its retained source path. Rendering and previews that require unresolved media must block with a list of missing files rather than silently substitute blank paper. Explicitly blank pages (None) remain blank. Saving preserves every absent reference. A malformed file must leave the current open project unchanged.

### Book templates

Keep the existing folder schema under %APPDATA%/Handyman/books. Validate editable fields, preserve unknown JSON fields where reasonable, use atomic book.json saves with .bak recovery, and copy new emblems without corrupting the previous reference if the copy fails. Existing templates remain accessible and untouched unless deliberately edited.

## 5. Phase 2 — Rendering and process lifecycle

Keep Blender and FFmpeg external; do not change their existing job/output naming. One worker owns one render lifecycle: pending -> rendering -> encoding -> completed / failed / cancelled. Exactly one terminal result is delivered, including for directory, JSON, subprocess, and encoding errors.

Introduce a small process-running or cancellation helper (render_process.py), called by RenderWorker and encode.py. Cancellation must terminate the active Blender or FFmpeg child, wait for reaping, and leave produced PNG frames in their output directory. It must not kill unrelated programs. Closing the window during active work must wait for termination or refuse closure with a clear message; never destroy a running QThread. A failed encoding does not delete frames. Preserve diagnostic logs and stderr tails.

## 6. Phase 3 — Export validity and editor acceptance

Keep 8-bit RGBA PNG intermediate files, ProRes 4444 MOV, and VP9 WebM; retain current names/codec defaults. Add FFprobe checks for streams, dimensions, pixel formats or VP9 alpha_mode metadata. In addition, encode a synthetic transparent test sequence and decode samples with a supported decoder to prove the alpha plane is actually non-opaque outside test shapes. For VP9, choose an alpha-capable decoder and document its limitations. No blanket guarantee for arbitrary editing programs follows from FFprobe metadata.

Manual Windows acceptance, recorded with app and editor versions: render a representative animated book to 1080p MOV and optional WebM; place over colored footage in Filmora; confirm transparent surroundings, correct page art, duration, frame ordering, and audio-free overlay. Keep a known-good output sample or reproducible test recipe. User confirmation is required for the Filmora gate.

## 7. Phase 4 — Tests and release discipline

Add pull_request triggers for fast tests and packaged-Windows smoke. Ensure an installed/frozen EXE is actually launched in a dedicated noninteractive smoke mode, rather than checking file existence only. Gate candidate releases on fast tests, a real Blender sample render, export alpha tests, and Windows startup. A failing required gate blocks publication.

Reduce independent push-to-main auto-publishing risk: publish only through a workflow whose required gates succeeded, or an explicitly approved release dispatch/tag. Preserve installer download artifacts for inspection. A PR need not publish a release. Where software OpenGL/EEVEE cannot run on a CI runner, clearly designate that check optional, retain a mandatory supported Blender render path, and make its failure visible.

## 8. Phase 5 — Safer updates

Retain repository-ID-based update lookup and explicit user consent. Publish a SHA-256 digest for each installer and verify downloaded bytes before executing; compare expected filename and version with trusted release metadata; validate HTTPS GitHub-origin asset URLs and use a unique temporary download directory. Reject missing or mismatched required integrity data for new releases. Allow cancellation that actually stops the download. Protect user data outside the installation folder. Do not silently claim strong publisher authenticity from an unsigned checksum; code-signing or signed release metadata remains a separately tracked future enhancement.

Update flow: check -> download -> verify -> prompt/confirm if needed -> launch installer -> exit application. Failure at any step leaves the current installed application usable, with an actionable error and no unverified executable launched. Test interrupted transfers, renamed assets, truncated files, wrong digests, and process start errors.

## 9. Phase 6 — Minimal extensibility boundary

Retain the functioning book-specific geometry and render implementation. Once phases 1–5 stabilize, move project persistence, process ownership, and output validation into small tested modules if not already isolated. Define a thin animation/template contract around existing book job creation and validation (e.g., a BookAnimation adapter); keep the existing book interface and Blender job schema. Do not introduce a speculative full plugin marketplace or rewrite renderer classes. A second animation type remains explicitly out of scope.

## 10. Observability, test matrix, and acceptance

New pure-Python tests follow the existing direct-script test convention and run under Python 3.12. Use fake processes for deterministic cancellation tests, local temporary directories for persistence tests, real FFmpeg for alpha integration tests when installed, and a real Blender sample in CI. The complete existing fast suite remains green. For Windows, verify fresh install, upgrade, live preview/fallback, project reopen, cancellation, and Filmora overlay manually before release.

Acceptance evidence belongs on the corresponding phase PR: test names/commands and outputs, changes made, remaining risks, and screenshot or clip evidence where practical. Each phase must have a rollback route (revert its PR) and avoid destructive data migrations.

## 11. Rollout and risks

Order: (1) projects/templates, (2) render/process, (3) alpha/export, (4) gates, (5) updater, (6) limited refactor. Each phase is independently reviewable; later phases depend on contract stability from earlier ones. A failed phase does not require the next phase to land.

Known risks: user project paths vary by machine; Qt/OpenGL drivers vary; Blender APIs change; Windows antivirus may warn on unsigned installers; FFmpeg VP9 alpha decoding varies by build; Filmora import behavior cannot be proved by Linux CI. Do not collapse these risks into a single green badge.

## 12. Non-goals

Android version, new animation categories, Blender engine replacement, automated art generation, cloud sync, a new UI toolkit, unrequested change of render quality, and rewriting the currently tested geometry are not included.
