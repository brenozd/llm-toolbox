---
name: screencapture
description: "Capture screenshots, videos and GIFs of the desktop, a web page, or a scripted real terminal (keys/clicks supported). Use for: \"take a screenshot\", \"record a gif/video of this CLI/page\", \"screencapture\", /screencapture, /screenshot."
allowed-tools:
  - Bash
  - Read
metadata:
  version: "0.1.0"
---

# screencapture

Capture screenshots (png/jpeg) and recordings (mp4/webm/gif) of the desktop, web pages and terminals.

## Trigger

User says: "screenshot", "capture the screen/window/region", "screenshot this page/URL",
"screenshot localhost:PORT", `/screenshot`, or `/screencapture`. For "record/gif/video" use `--record` (below).

## Workflow

1. Decide the capture target from the user's request:
   - A running app / the desktop / a window / a region → desktop capture.
   - A URL (including `localhost`) → web capture (`--web`).
2. Run the script from the repo root or the user's project cwd, so `.screenshots/`
   lands in a sensible place:

   ```bash
   python3 <path-to-this-skill>/scripts/screencapture.py [flags]
   ```

   Common invocations:

   ```bash
   # Full screen
   python3 scripts/screencapture.py --mode full

   # Active window
   python3 scripts/screencapture.py --mode window

   # Interactive region select
   python3 scripts/screencapture.py --mode region

   # Web page, full scrollable page, resized for fewer tokens
   python3 scripts/screencapture.py --web http://localhost:3000 --small

   # Web page, visible viewport only
   python3 scripts/screencapture.py --web https://example.com --viewport

   # Mobile viewport, plus DOM dump for debugging CSS
   python3 scripts/screencapture.py --web http://localhost:3000 --mobile --dom
   ```

3. The script prints the saved file path(s) on stdout (image, and `.html` if
   `--dom` was used). `Read` the image path to view it inline and reason about it.
4. If the user wants it on the clipboard instead of (or in addition to) a file,
   add `--clipboard`.
5. To review or clean up past captures this session: `--list` / `--clear` /
   `--clear-yes`.

## Recording (video / gif)

Add `--record term|gui|web|desktop`; output ext decides the format (`--gif` = .gif, default .mp4;
`--output x.webm` also works). `Read` cannot play video: report the path, or grab a frame with ffmpeg.

```bash
# real xterm on a virtual X display (needs Xvfb, xterm, xdotool, ffmpeg, script)
python3 scripts/screencapture.py --record term --gif --cwd /repo --steps '[{"type":"type","text":"make test"},{"type":"key","key":"Return"},{"type":"wait_for","text":"passed","timeout_s":60}]'
# web page via Playwright, with a visible cursor; steps use selectors or x/y
python3 scripts/screencapture.py --record web --web http://localhost:3000 --steps steps.json
# any GUI app on a private X display (forced to X11, window stretched to --web-width/height at 0,0, so click x/y = window coords)
python3 scripts/screencapture.py --record gui --app kcalc --steps '[{"type":"type","text":"12*34"},{"type":"key","key":"Return"},{"type":"click","x":640,"y":360}]'
# the real desktop, no input (spectacle on KDE, wf-recorder on wlroots, x11grab, avfoundation, gdigrab)
python3 scripts/screencapture.py --record desktop --seconds 8 --gif
```

Steps (JSON list or file): `type`, `key`, `click` (x,y or selector, `button` 1-3), `move`, `scroll` (`dy`),
`wait_for` (text/selector, `timeout_s`), `hold_s`, and `goto` (web). `key` is an xdotool keysym in
term (`Return`, `ctrl+c`) and a Playwright key in web (`Enter`, `Control+c`). term, gui, web and desktop recordings write a
`.json` receipt beside it (typed text and shell output are left out unless `--keep-output`; a secret-looking string only raises a warning). Missing tools are reported with the install command. `gui` needs Xvfb, xdotool, ffmpeg; no
`wait_for`/selectors there (use `hold_s`, x/y). Wayland-only apps are not supported yet.

For a storyboard-video clip add `--format 16:9|9:16`: it sets the terminal grid/font and the gui/web window to
the server's geometry (explicit `--cols/--rows/--font/--size` win). Without it the old defaults apply.

## Trust model

Recording runs on the host with the shell's powers: `--app` launches any command, `--setup` is raw shell sourced in
the recorded bash, `type` steps are keystrokes into a real shell, web pages load in a `--no-sandbox` Chromium
fallback, and `--clear` deletes tracked files. Treat steps from an untrusted source like untrusted code: run them in
the `distrobox` skill or the `storyboard-video-exec` container. The video is never redacted, and `desktop`
(experimental, untested here) records the whole screen, notifications included.

## Flags

See `README.md` for the full flag reference.

## Notes

- Desktop capture auto-picks a backend for the current OS/session (see README)
  and needs a live graphical session — it can't run headless.
- Web capture needs `chromium-browser`/`chromium`/`google-chrome` on PATH (or,
  on macOS, in `/Applications`).
- Defaults to `.screenshots/` in the current working directory; pass `--output PATH`
  for an explicit location.
- Run `python3 scripts/screencapture.py --selftest` to sanity-check the resize/format,
  CDP-capture, and DOM-capture logic without touching the desktop.
