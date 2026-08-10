---
name: screenshot
description: |
  Capture a desktop or web-page screenshot (Python + Pillow, styled after claudeshot).
  Desktop capture auto-detects a backend per OS (spectacle/grim/gnome-screenshot/scrot/maim/
  import on Linux, screencapture on macOS, Pillow ImageGrab on Windows). Web capture via
  headless Chromium + CDP, with optional DOM/HTML dump, mobile/tablet viewport presets, and
  full-page or viewport-only shots. Resize/format conversion via Pillow. Clipboard copy on
  all three OSes. Session tracking with list/clear. Cross-platform: Linux, macOS, Windows.
  Use when: "screenshot", "take a screenshot", "capture the screen", "screenshot this page",
  "screenshot localhost", "capture this window", "screenshot mobile view", "list screenshots",
  "clear screenshots", "/screenshot".
allowed-tools:
  - Bash
  - Read
---

# screenshot

Capture desktop or web-page screenshots and view them inline.

## Trigger

User says: "screenshot", "capture the screen/window/region", "screenshot this page/URL",
"screenshot localhost:PORT", or `/screenshot`.

## Workflow

1. Decide the capture target from the user's request:
   - A running app / the desktop / a window / a region → desktop capture.
   - A URL (including `localhost`) → web capture (`--web`).
2. Run the script from the repo root or the user's project cwd, so `.screenshots/`
   lands in a sensible place:

   ```bash
   python3 <path-to-this-skill>/scripts/shot.py [flags]
   ```

   Common invocations:

   ```bash
   # Full screen
   python3 scripts/shot.py --mode full

   # Active window
   python3 scripts/shot.py --mode window

   # Interactive region select
   python3 scripts/shot.py --mode region

   # Web page, full scrollable page, resized for fewer tokens
   python3 scripts/shot.py --web http://localhost:3000 --small

   # Web page, visible viewport only
   python3 scripts/shot.py --web https://example.com --viewport

   # Mobile viewport, plus DOM dump for debugging CSS
   python3 scripts/shot.py --web http://localhost:3000 --mobile --dom
   ```

3. The script prints the saved file path(s) on stdout (image, and `.html` if
   `--dom` was used). `Read` the image path to view it inline and reason about it.
4. If the user wants it on the clipboard instead of (or in addition to) a file,
   add `--clipboard`.
5. To review or clean up past captures this session: `--list` / `--clear` /
   `--clear-yes`.

## Flags

See `README.md` for the full flag reference.

## Notes

- Desktop capture auto-picks a backend for the current OS/session (see README)
  and needs a live graphical session — it can't run headless.
- Web capture needs `chromium-browser`/`chromium`/`google-chrome` on PATH (or,
  on macOS, in `/Applications`).
- Defaults to `.screenshots/` in the current working directory; pass `--output PATH`
  for an explicit location.
- Run `python3 scripts/shot.py --selftest` to sanity-check the resize/format,
  CDP-capture, and DOM-capture logic without touching the desktop.
