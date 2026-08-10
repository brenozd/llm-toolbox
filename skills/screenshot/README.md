# screenshot

Captures desktop or web-page screenshots with Python + Pillow, styled after
[claudeshot](https://github.com/naieum/claudeshot). Cross-platform: Linux
(Wayland or X11), macOS, Windows.

Pillow itself only does image processing — no screen capture, clipboard
write, or DOM support. `PIL.ImageGrab.grab()` covers full-screen capture on
Windows/macOS (and X11 Linux with `python3-xlib`), which this script uses on
Windows; everywhere else it shells out to an OS-native tool, same as
claudeshot does.

## Trigger

`/screenshot`, or phrases like "screenshot", "capture the screen", "screenshot
this page", "screenshot localhost:3000", "screenshot mobile view".

## Usage

```bash
python3 scripts/shot.py [flags]
```

## Flags

| Flag | Effect |
|---|---|
| `--mode full\|window\|region` | Desktop capture mode (default `full`). Ignored if `--web` is set. |
| `--web URL` | Screenshot a web page via headless Chromium instead of the desktop. |
| `--web-width N` / `--web-height N` | Chromium viewport size (default 1280x800). |
| `--mobile` | Mobile viewport (390x844). |
| `--tablet` | Tablet viewport (768x1024). |
| `--viewport-size WxH` | Custom viewport, e.g. `375x667`. |
| `--viewport` | Capture only the visible viewport, not the full scrollable page. |
| `--dom` | Also save the page's rendered HTML alongside a `--web` screenshot. |
| `--delay N` | Delay N seconds before desktop capture. |
| `--output PATH` | Explicit output path (default `.screenshots/shot-<timestamp>.png`). |
| `--resize N` | Resize to N px width, keep aspect ratio. |
| `--small` | Resize to 1280px width. |
| `--tiny` | Resize to 640px width. |
| `--jpeg` | Save as JPEG instead of PNG. |
| `--clipboard` | Also copy the result to the clipboard. |
| `--list` | List this session's captured screenshots and exit. |
| `--clear` | Delete this session's screenshots (asks for confirmation). |
| `--clear-yes` | Delete this session's screenshots, no prompt. |
| `--selftest` | Run the self-check (resize/format, CDP capture, DOM capture) and exit. |

## Examples

```bash
# Full screen, saved to .screenshots/
python3 scripts/shot.py

# Region select, straight to clipboard
python3 scripts/shot.py --mode region --clipboard

# Full-page web screenshot, resized
python3 scripts/shot.py --web http://localhost:3000 --small

# Web viewport only, as JPEG
python3 scripts/shot.py --web https://example.com --viewport --jpeg

# Mobile viewport + DOM dump, for debugging a CSS issue
python3 scripts/shot.py --web http://localhost:3000 --mobile --dom

# Review and clean up this session's captures
python3 scripts/shot.py --list
python3 scripts/shot.py --clear
```

## Platform support

| | Desktop capture | Clipboard | Web capture |
|---|---|---|---|
| Linux (Wayland) | `spectacle`, else `grim`+`slurp` | `wl-copy`, else `xclip`/`xsel` | headless Chromium/Chrome |
| Linux (X11) | `spectacle`, `gnome-screenshot`, `scrot`, `maim`, or `import` (ImageMagick) | `xclip`/`xsel` | headless Chromium/Chrome |
| macOS | `screencapture` (built-in) | `osascript` (built-in) | headless Chrome/Chromium |
| Windows | `PIL.ImageGrab.grab()` (full screen only — interactive window/region selection isn't scriptable without extra deps) | Win32 clipboard via `ctypes` (stdlib) | headless Chrome |

Desktop capture tool is auto-detected at runtime; the first one found on PATH
(in the order above) wins.

## Requirements

- Python 3 + Pillow
- One of the desktop-capture tools above, present already on most desktop Linux/macOS installs
- `chromium-browser` / `chromium` / `google-chrome` on PATH (or `/Applications` on macOS) for web capture
