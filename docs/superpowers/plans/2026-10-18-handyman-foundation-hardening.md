# Handyman Foundation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Harden the existing Handyman 0.5.0 Windows book-animation application across six phases without breaking current projects, user templates, live preview, rendering, or exports.

**Architecture:** Keep PySide6 and the shared book geometry. Extract a small persistence boundary and a process-lifecycle helper, add export validation and stricter release/update safeguards, then introduce a narrow book-animation adapter after behavioral tests exist. Each phase is a separate independently reviewable PR; the steps below specify the intended interfaces.

**Tech Stack:** Python 3.12, PySide6 6.10.2, NumPy 2.3.3, PyOpenGL 3.1.9, Blender (external), FFmpeg/FFprobe (external), PyInstaller 6.16.0, Inno Setup, GitHub Actions.

**Spec:** docs/superpowers/specs/2026-10-18-handyman-foundation-hardening-design.md

**Baseline:** Handyman 0.5.0, main commit 01ce147e03a8d6b4cce0935a138f4ddaf5c44eaa

## Global Constraints

- Existing unversioned .hmproj projects and user-created templates under %APPDATA%/Handyman/books remain readable.
- Do not discard missing-image paths, change page ordering, delete source assets, or overwrite user data on errors.
- No geometry/timing/camera algorithm rewrite, Blender job-format change, new animation type, or framework migration.
- Keep the v0.5.0 published release intact; implement on isolated topic branches and do not automatically merge.
- Every behavioral change: failing regression test first, confirm expected failure, minimal fix, new test green, complete current fast suite green, commit, code review.
- Windows x64 is the shipping platform. Linux Blender sampling complements rather than replaces Windows desktop and Filmora acceptance.
- Required CI checks must block publication. Do not describe optional checks as pass requirements.
- No user-facing release before Windows/Filmora acceptance is recorded.
- New modules must be pure Python where possible, avoiding unnecessary dependencies.

## Review Focus

These are the five likely real-user failures that must be pinned to an owning task's tests:
1. Project moved to another folder, with some page images missing: keep positions and paths, show missing-media warning, block unsafe rendering (Tasks 2–3).
2. Filesystem write or copy fails halfway: original .hmproj/book.json and emblem stay recoverable (Tasks 1 and 4).
3. Cancel immediately after Blender completes while FFmpeg runs: FFmpeg stops, frames remain, and no running QThread is destroyed (Tasks 5–6).
4. Transparent frames encoded into MOV/WebM with an opaque video plane despite successful FFmpeg exit: verification rejects it (Task 7).
5. Wrong/truncated update download or installer launch failure: never execute the bytes; keep installed Handyman usable (Tasks 11–12).

## Baseline and recurring verification

At the start of each implementation phase:
- Pull latest main, create a fresh branch named foundation/phase-N-<short-name>, inspect existing PRs, and keep version.py unchanged until the verified release process is ready.
- Run the existing fast suite in the working checkout:
  - python test_curl.py
  - python test_support.py
  - python test_camera.py
  - python test_model.py
  - python test_scene_mock.py
  - python test_app_smoke.py
- Record pass/fail output. Do not merge on a failed baseline.
- New tests use unittest in top-level test_*.py and run with python -m unittest -v <module>. Add each new test module to the workflow test step.
- At each task's green step, run its targeted test **and the entire existing fast suite** (plus new modules introduced so far); only commit when those commands exit 0.
- Have a reviewer read the diff and test evidence before progressing; fix Critical and Important issues before the next task or merge.

---

## Phase 1 — Projects and templates

### Task 1: Atomic save and load of project JSON

**Files:**
- Create: project_store.py (pure-Python persistence)
- Create: test_project_store.py
- Modify: app.py (_save_project, _open_project)

**Interfaces:**
- Produces: ProjectFormatError(ValueError), load_project(path: Path) -> dict, save_project(path: Path, state: dict) -> None.
- The saved object has schema_version=1; absent schema_version is legacy and supported. Unknown future versions fail before UI mutation.
- Save via temporary sibling + flush + os.replace; after a successful initial save, further overwrites retain a recoverable .bak of the prior project.

- [ ] **Step 1 — RED:** Write unittest tests named test_legacy_project_loads, test_bad_json_does_not_mutate_existing_file, test_atomic_write_failure_keeps_original, test_repeated_save_keeps_backup, and test_future_schema_rejected. Use TemporaryDirectory; inject/patch os.replace only for the failure test. Assert file bytes, backup contents, and exception type.
- [ ] **Step 2 — Verify red:** python -m unittest -v test_project_store; expected targeted failures because project_store does not exist.
- [ ] **Step 3 — GREEN:** Implement the exact functions above and wire app.py to call them. For open, parse and validate all data before applying changes. Use no temporary files outside the destination volume.
- [ ] **Step 4 — Verify green:** python -m unittest -v test_project_store; run the recurring full fast suite including test_app_smoke.py; all pass.
- [ ] **Step 5 — Commit:** git add project_store.py test_project_store.py app.py && git commit -m "fix: save and load projects safely".

### Task 2: Portable references while preserving legacy paths

**Files:**
- Modify: project_store.py
- Modify: test_project_store.py
- Modify: app.py (_save_project, _open_project)

**Interfaces:**
- Produces: prepare_project_state(state: dict, project_path: Path) -> dict and resolve_project_state(state: dict, project_path: Path) -> dict.
- New relative media paths are relative to the .hmproj directory; absolute refs remain valid, including paths on another Windows drive. None always signifies an intentionally blank page. No media is copied.

- [ ] **Step 1 — RED:** Add test_relative_images_survive_project_folder_move, test_absolute_legacy_images_stay_usable, test_cross_drive_path_does_not_throw, test_blank_pages_keep_none, and test_failed_resolution_keeps_original_reference. Use paths with spaces and mixed PNG/JPEG suffixes.
- [ ] **Step 2 — Verify red:** python -m unittest -v test_project_store; newly added cases fail for missing helpers or wrong stored paths.
- [ ] **Step 3 — GREEN:** Implement the two functions, preserving input key/value semantics and using pathlib/os.path only; integrate at save/open boundaries.
- [ ] **Step 4 — Verify green:** targeted project tests and recurring full suite; check old .hmproj files remain readable.
- [ ] **Step 5 — Commit:** git add project_store.py test_project_store.py app.py && git commit -m "fix: preserve portable project image references".

### Task 3: Missing media is visible and never silently removed

**Files:**
- Modify: app.py (_set_pages, _pages_changed, _open_project, _preview_still, _preview_anim, _render)
- Modify: test_app_smoke.py

**Interfaces:**
- Produces: Studio._missing_pages() -> list[tuple[int, str]] with 1-based page positions.
- _set_pages must append a page item even when the file is missing, return the missing count, and label missing items distinctly. Render/preview entrypoints reject missing nonblank source paths, without clearing the project.

- [ ] **Step 1 — RED:** Extend the offscreen smoke test: load three pages with a deliberately nonexistent middle image; assert pages.count()==3, the middle UserRole retains the path after save/reopen, and _missing_pages() reports position 2. Test that rendering is blocked before _scratch() destroys previous preview files.
- [ ] **Step 2 — Verify red:** QT_QPA_PLATFORM=offscreen python test_app_smoke.py (set environment with PowerShell syntax on Windows); expected failure because missing path is currently skipped.
- [ ] **Step 3 — GREEN:** Implement missing-path preservation and a user-visible warning; avoid silent blank-page substitution in all three render entrypoints. Do not change intentionally blank-page handling.
- [ ] **Step 4 — Verify green:** test_app_smoke.py and recurring full suite. Manual UI check: reopen project containing a missing middle page.
- [ ] **Step 5 — Commit:** git add app.py test_app_smoke.py && git commit -m "fix: retain missing project media and page order".

### Task 4: Safe editing and recovery of custom book templates

**Files:**
- Modify: templates.py
- Modify: test_support.py
- Modify: book_dialog.py only if a validation error needs UI presentation

**Interfaces:**
- Retains: templates.load(folder) -> dict and templates.save(book, new_image=None) -> dict.
- book.json updates are atomic with a .bak; incomplete emblem copies never replace a previously referenced file. Validate colors and numeric fields before writing; reject invalid edits with actionable errors instead of corrupting the saved book.

- [ ] **Step 1 — RED:** Add test_failed_template_write_preserves_original, test_failed_emblem_copy_retains_old_image, test_invalid_colors_are_rejected_before_save, test_legacy_template_still_loads, and test_unknown_fields_survive_edit where compatible. Simulate IOError with a patched copy/write operation.
- [ ] **Step 2 — Verify red:** python test_support.py; new tests fail in the expected data-protection cases.
- [ ] **Step 3 — GREEN:** Replace in-place writes with sibling temporary files and replacement, keep old emblem assets until the new reference is safely saved, and add validation. Maintain existing default-template behavior and image preview.
- [ ] **Step 4 — Verify green:** test_support.py and recurring full suite; exercise copy/edit in the real UI.
- [ ] **Step 5 — Commit:** git add templates.py test_support.py book_dialog.py && git commit -m "fix: protect custom book edits".

---

## Phase 2 — Process and render reliability

### Task 5: Single owner for external subprocesses

**Files:**
- Create: render_process.py
- Create: test_render_process.py
- Modify: app.py (RenderWorker, closeEvent)

**Interfaces:**
- Produces: ProcessSession class with run(command: list[str], on_line: Callable[[str], None] | None = None) -> int, cancel() -> None, and cancelled: bool.
- A session owns at most one active child. cancel terminates/reaps only that child. A completed or cancelled worker emits exactly one terminal signal. Window closure waits for safe completion or refuses closure while cancellation is pending.

- [ ] **Step 1 — RED:** Tests test_cancel_terminates_running_child, test_cancel_before_start_prevents_launch, test_spawn_exception_is_reported, and test_process_exit_without_done_is_failure. Use sys.executable as the short-lived/sleeping child, not a mocked return code; offscreen UI test verifies the worker lifetime rule.
- [ ] **Step 2 — Verify red:** python -m unittest -v test_render_process and python test_app_smoke.py; expected failures for missing ProcessSession and lifecycle edge cases.
- [ ] **Step 3 — GREEN:** Add session and wire RenderWorker to use it. Retain Blender PROGRESS/ERROR/DONE parsing, ensure directory/job.json errors signal failure, and do not report success without DONE and zero exit code.
- [ ] **Step 4 — Verify green:** targeted tests and recurring full suite. Manually cancel a real Blender render.
- [ ] **Step 5 — Commit:** git add render_process.py test_render_process.py app.py && git commit -m "fix: own Blender process lifecycle and cancellation".

### Task 6: Cancel encoding without deleting PNG frames

**Files:**
- Modify: encode.py
- Modify: app.py (RenderWorker._encode and cancel)
- Modify: test_render_process.py
- Create: test_encode.py

**Interfaces:**
- Extend encode_mov(folder, fps, name=..., session: ProcessSession | None = None) -> Path and encode_webm(folder, fps, quality=28, name=..., session: ProcessSession | None = None) -> Path. Existing calls without session remain valid.
- _run accepts an optional ProcessSession and raises a clear exception on cancellation or nonzero FFmpeg exit. Only successful complete encoding permits deleting PNG intermediates.

- [ ] **Step 1 — RED:** Add test_cancel_during_encode_keeps_png_frames, test_ffmpeg_failure_does_not_delete_frames, test_finished_encoding_cleans_only_when_requested, and test_existing_encode_function_calls_remain_compatible.
- [ ] **Step 2 — Verify red:** python -m unittest -v test_encode test_render_process; expected cancellation/failure cases fail.
- [ ] **Step 3 — GREEN:** Pass the worker-owned ProcessSession to FFmpeg, always reap active children, check cancellation before deleting frames, and preserve partial outputs/diagnostics.
- [ ] **Step 4 — Verify green:** targeted tests and recurring full suite; manual cancel while FFmpeg is visibly encoding.
- [ ] **Step 5 — Commit:** git add encode.py app.py test_render_process.py test_encode.py && git commit -m "fix: support cancellable encoding and preserve frames".

---

## Phase 3 — Alpha exports

### Task 7: Validate video codec, alpha plane, and output dimensions

**Files:**
- Create: alpha_validation.py
- Create: test_alpha_validation.py
- Modify: encode.py

**Interfaces:**
- Produces: verify_export(path: Path, kind: str, expected_width: int | None = None, expected_height: int | None = None) -> None; raises ExportValidationError on mismatch.
- Accepted kind is mov or webm. Probe stream metadata with ffprobe and sample decoded RGBA frames using FFmpeg (explicit VP9-capable alpha decoder when necessary). A fully opaque test source must fail if it is expected to contain transparency. Missing ffprobe must surface a non-success outcome for required verification.

- [ ] **Step 1 — RED:** Create short transparent and opaque PNG sequences in a temp directory with Qt QImage. Add test_mov_retains_transparent_corner, test_webm_retains_transparent_corner, test_opaque_video_is_rejected, test_wrong_dimensions_rejected, and test_missing_ffprobe_rejected. Skip integration only when FFmpeg is absent locally; CI must install it and not skip.
- [ ] **Step 2 — Verify red:** python -m unittest -v test_alpha_validation; expected failure for absent validator or opacity check.
- [ ] **Step 3 — GREEN:** Implement metadata and decoded-alpha verification, call only after FFmpeg reports success, and keep PNG frames when it fails. Avoid adding Pillow to runtime requirements.
- [ ] **Step 4 — Verify green:** targeted alpha tests, recurring full suite, and one real transparent book export using Blender in CI.
- [ ] **Step 5 — Commit:** git add alpha_validation.py test_alpha_validation.py encode.py && git commit -m "test: verify actual alpha in encoded exports".

### Task 8: Record real Filmora acceptance (manual release gate)

**Files:**
- Create: docs/acceptance/filmora-alpha.md
- Update: README.md (link to acceptance protocol)

**Interfaces:**
- Test recipe explicitly records OS, Handyman/Blender/FFmpeg/Filmora versions, source project, MOV/WebM formats, expected transparent surroundings, duration, frame order, frame size, and pass/fail screenshot.
- A real Windows/Filmora pass is required before publishing a production version; Linux CI alone cannot satisfy it.

- [ ] **Step 1:** Write the reproducible steps for rendering a 1080p book overlay and placing it over a solid bright color and regular footage in Filmora.
- [ ] **Step 2:** Add a results table with untested as its initial status, not a fabricated pass.
- [ ] **Step 3:** Confirm the protocol covers opacity, page orientation, timing, motion, and playback; link the protocol in README.md.
- [ ] **Step 4:** Commit: git add docs/acceptance/filmora-alpha.md README.md && git commit -m "docs: define Filmora transparency acceptance".

---

## Phase 4 — Release gates

### Task 9: Actually start the frozen Windows application

**Files:**
- Modify: app.py (noninteractive --smoke-test mode only)
- Modify: test_app_smoke.py
- Modify: .github/workflows/release.yml

**Interfaces:**
- Running Handyman.exe --smoke-test with QT_QPA_PLATFORM=offscreen constructs and closes the main window, exits 0 on success or nonzero with a diagnostic on failure, without starting Blender or performing an update check.
- The workflow runs it with a timeout after PyInstaller, rather than treating file existence as successful startup.

- [ ] **Step 1 — RED:** Test sys.argv smoke invocation using subprocess and a timeout. Verify a healthy app exits 0, while an injected initialization failure exits nonzero.
- [ ] **Step 2 — Verify red:** python test_app_smoke.py; current app has no smoke-test CLI path.
- [ ] **Step 3 — GREEN:** Add a small smoke entry in app.py, disable update startup checks in smoke mode, and call built executable from release.yml.
- [ ] **Step 4 — Verify green:** test_app_smoke.py, recurring full suite, and a Windows GitHub Actions run of dist/Handyman/Handyman.exe --smoke-test.
- [ ] **Step 5 — Commit:** git add app.py test_app_smoke.py .github/workflows/release.yml && git commit -m "ci: smoke-test packaged Handyman executable".

### Task 10: Require test and render gates before release publication

**Files:**
- Modify: .github/workflows/release.yml
- Modify: .github/workflows/preview.yml only to clarify optional vs required behavior
- Modify: README.md (release procedure)

**Interfaces:**
- PR event builds and runs tests, never publishes. A required Blender sample + alpha integration check and packaged-Windows startup precede any release job.
- Push to main builds and tests but does not publish automatically before Filmora manual acceptance. A manual release action with recorded acceptance and successful required jobs may publish the current version. Version/changelog checks must be part of the gate.

- [ ] **Step 1 — RED:** Add a workflow-focused check/test (e.g. test_workflows.py parsing YAML as text with strict assertions) that fails while publication is unconditional on push-to-main and required checks are absent.
- [ ] **Step 2 — Verify red:** python -m unittest -v test_workflows; expected failures for publication gate and missing PR trigger.
- [ ] **Step 3 — GREEN:** Split required test/render/package jobs and give publishing explicit needs. Include alpha tests from Task 7 and a real Blender sample. Classify headless EEVEE as optional only if a mandatory supported Blender renderer still passes. Add manual acceptance input or reviewed environment gate.
- [ ] **Step 4 — Verify green:** test_workflows.py and recurring suite; inspect a real PR Actions run and a deliberately broken test on a throwaway branch, proving publication is skipped.
- [ ] **Step 5 — Commit:** git add .github/workflows/release.yml .github/workflows/preview.yml README.md test_workflows.py && git commit -m "ci: require acceptance and tests before publishing".

---

## Phase 5 — Update download safety

### Task 11: Bind installer bytes to release checksum

**Files:**
- Modify: updater.py
- Modify: test_support.py
- Modify: .github/workflows/release.yml

**Interfaces:**
- release.yml publishes Handyman-Setup-V.exe and matching SHA-256 data (.sha256 companion asset or SHA-256 digest in GitHub asset metadata).
- updater.check() returns validated version, expected installer name/size/URL, and expected SHA-256 digest for new releases; updater.download(info, progress=None, ..., cancel_event=None) -> Path verifies both length and SHA-256 before returning the executable.
- Reject unexpected filenames, non-HTTPS hosts, missing new-release integrity metadata, wrong hashes, and truncated output. A plain unsigned hash proves integrity relative to GitHub metadata, not strong publisher identity.

- [ ] **Step 1 — RED:** Tests test_missing_checksum_rejects_update, test_wrong_hash_never_returns_executable, test_truncated_download_removed, test_unexpected_asset_name_rejected, and test_valid_hash_allows_download. Use local fake HTTP response objects; never execute a downloaded test file.
- [ ] **Step 2 — Verify red:** python test_support.py; new hash cases fail under current updater.
- [ ] **Step 3 — GREEN:** Add release checksum generation to CI, validated trusted-URL/version parsing and incremental SHA-256 in updater.py, use a uniquely named temp directory, and remove invalid downloads.
- [ ] **Step 4 — Verify green:** test_support.py, recurring full suite, and a release-draft checksum comparison using real artifact bytes.
- [ ] **Step 5 — Commit:** git add updater.py test_support.py .github/workflows/release.yml && git commit -m "security: verify installer integrity before updates".

### Task 12: Cancel and recover failed updates

**Files:**
- Modify: updater.py
- Modify: app.py (UpdateDownload, _offer_update, _install_update)
- Modify: test_support.py
- Modify: test_app_smoke.py

**Interfaces:**
- UpdateDownload owns a threading.Event cancellation token passed into updater.download. The cancel button sets the token and the worker actually stops before installer launch. _install_update traps subprocess launch errors, keeps running app usable, and never quits until launch succeeds.

- [ ] **Step 1 — RED:** Add test_midstream_cancel_removes_temp_file, test_cancel_never_launches_installer, test_installer_spawn_failure_keeps_ui_running, and test_older_installed_version_keeps_user_books. Use deterministic streamed chunks/fake Popen where appropriate.
- [ ] **Step 2 — Verify red:** targeted test_support.py and test_app_smoke.py; existing cancel behavior cannot terminate a download.
- [ ] **Step 3 — GREEN:** Wire cancel event to QProgressDialog, stop the transfer, clean temp artifacts, catch Popen errors, and preserve settings/books under user_dir() outside the installer path.
- [ ] **Step 4 — Verify green:** targeted tests and recurring full suite. Exercise update cancellation and failed download on Windows.
- [ ] **Step 5 — Commit:** git add updater.py app.py test_support.py test_app_smoke.py && git commit -m "fix: make updates cancellable and recoverable".

---

## Phase 6 — Small extensibility refactor

### Task 13: Introduce a book-animation adapter without new features

**Files:**
- Create: book_animation.py
- Create: test_book_animation.py
- Modify: app.py (_job, _timeline only)
- Keep unchanged: book_scene.py, book_model.py, page_curl.py, camera_fit.py, live_view.py unless an explicitly verified behavior difference requires a follow-up.

**Interfaces:**
- Produces: BookAnimation.create_job(settings: dict, book: dict, images: list, out_dir: Path, **overrides) -> dict, delegating to blender_bridge.make_job.
- Produces: BookAnimation.timeline(pages_count: int, settings: dict, turns_override: int | None = None) -> Timeline, matching current Studio._timeline and preserving the shortened two-turn draft preview.
- BookAnimation.id = "book-page-turn". No plugin loading, new renderer, or animation marketplace in this phase.

- [ ] **Step 1 — RED:** Add test_adapter_job_matches_existing_bridge and test_adapter_timeline_matches_existing_app for existing camera presets, closed/open book, 1/2/5/8 page counts, and turns_override=2 (draft preview); verify job JSON equivalence and matching timeline frame counts/timing, not just object identity.
- [ ] **Step 2 — Verify red:** python -m unittest -v test_book_animation; class absent.
- [ ] **Step 3 — GREEN:** Implement the small adapter and redirect only the two UI methods through it; retain public behavior and file naming.
- [ ] **Step 4 — Verify green:** targeted test, recurring full suite, real Blender preview comparison (first/mid/last), and OpenGL live-preview regression screenshots.
- [ ] **Step 5 — Commit:** git add book_animation.py test_book_animation.py app.py && git commit -m "refactor: isolate book animation job interface".

---

## Final acceptance and release

### Task 14: Confirm backward compatibility and publish only after approval

**Files:**
- Update: docs/acceptance/filmora-alpha.md with actual results
- Update: CHANGES.md and version.py only when release is approved
- Read: README.md and all phase PR test evidence

**Interfaces:** No new code API. The shipping decision requires current Windows installation and Filmora evidence.

- [ ] **Step 1:** Open a saved legacy v0.5.0 project, deliberately remove a middle image, confirm placeholder/path retention, restore image, save and reopen.
- [ ] **Step 2:** Verify a custom leather-journal copy and emblem edit survives installation/upgrade and file writes; no source image deleted.
- [ ] **Step 3:** Test 1, 2, 5, and 8 images; both opening modes, all camera presets, playback controls, start/pause/stop, Blender cancellation, FFmpeg cancellation, and missing Blender/FFmpeg scenarios.
- [ ] **Step 4:** Render a 1080p MOV with PNG preservation and a WebM. Verify decoded alpha automatically. Import MOV into Filmora on Windows and record transparency, timing, page order, and background-overlay result.
- [ ] **Step 5:** On real Windows, perform clean install, prior-version upgrade, deliberate wrong-checksum rejection, a cancelled update, and successful update; ensure custom books/projects persist.
- [ ] **Step 6:** Check every required Actions job has an actual successful completed result at the candidate commit; investigate rather than waive failures. Confirm no critical review items remain.
- [ ] **Step 7:** After the user authorizes release, bump version and changelog, invoke the manually gated release workflow, verify installer artifact/release checksum and updater discovery. Do not assume success before inspecting the workflow output.

## Execution strategy and stopping rules

Recommended: native task-by-task execution with an explicit independent code review at each phase boundary; if agent delegation is available, use fresh reviewer context for high-risk persistence, process, and updater changes.

- Each phase has its own PR and rollback via revert; do not stack unverified changes on main.
- Stop on failed baseline, unexpected changes to user data, missing manual Filmora acceptance, unsigned/unverifiable update claims, or CI gates that can pass without running required verification.
- Do not mark any item complete from the plan alone. Link the actual commit, test transcript, PR, and (where applicable) Windows screenshot/Filmora validation.
