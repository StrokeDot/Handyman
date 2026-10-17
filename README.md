# Handyman

Personal tool: 3D page-turn overlays with a transparent background, for layering in a video editor.
Blender does the 3D work in the background.

## Install

1. Install Blender (free): https://www.blender.org/download/
2. Download `Handyman-Setup-x.y.z.exe` from the latest release and run it.
   Windows may say "Windows protected your PC": click **More info → Run anyway** (the installer isn't paid-signed).
3. FFmpeg on PATH is needed for MOV/WebM export.

The app checks for new versions at startup and can install them itself.

## Use

- **Book**: pick a template, or *Make a copy…* and *Edit…* to design a new one (leather, paper, emblem, title, stitching).
  Templates live in `%APPDATA%\Handyman\books` and are never uploaded anywhere.
- **Pages**: add images in reading order. Page 1 is the left page, page 2 the right page; each turn shows the next two.
- **Preview still** first, then **Render video**. Each render gets its own folder with a transparent ProRes 4444 MOV
  (and optionally WebM and PNG frames).
- **Save project…** keeps the pages and settings for later.

If a render fails, the error box has **Show Details**: that text explains what went wrong.

## Releasing

Change `APP_VERSION` in `version.py` and add a section to `CHANGES.md`. Pushing to `main` builds the installer and
publishes the release; installed copies pick it up at their next start.

## Run from source

    py -3 -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python app.py

## Files

- `app.py`, `book_dialog.py` — the windows
- `book_scene.py` — builds and renders the book inside Blender
- `page_curl.py` — page-turn shape and timing
- `templates.py` — book templates
- `blender_bridge.py`, `encode.py` — run Blender and FFmpeg
- `updater.py`, `installer/`, `.github/workflows/` — installer and updates
- `test_*.py` — checks run on every build
