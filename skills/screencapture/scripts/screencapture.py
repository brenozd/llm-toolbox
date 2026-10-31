#!/usr/bin/env python3
"""Screenshot tool: desktop capture, web capture via headless Chromium + CDP,
resize/format conversion via Pillow, clipboard copy, DOM capture, session
tracking. Cross-platform: Linux (Wayland/X11), macOS, Windows.

Pillow itself has no screen-capture, clipboard-write, or DOM support --
those always go through an OS-native tool. Where Pillow *can* help
(ImageGrab.grab() on Windows/macOS/X11) it's used; everywhere else this
shells out, following claudeshot's tool-detection approach.
"""

import argparse
import base64
import json
import platform
import random
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:  # a missing Pillow is reported by main() with an install hint, not as a traceback
    from PIL import Image
    PILLOW_ERROR = ""
except ImportError as e:  # pragma: no cover - depends on the environment
    Image = None
    PILLOW_ERROR = str(e)

PILLOW_HINT = ("Pillow is required for resize/format conversion, web capture and --selftest: "
               "pip install Pillow (or: dnf install python3-pillow / apt install python3-pil)")


def _require_pillow() -> None:
    if Image is None:
        raise RuntimeError(PILLOW_HINT)


PRESETS = {"small": 1280, "tiny": 640}
VIEWPORTS = {"mobile": (390, 844), "tablet": (768, 1024)}

OS = platform.system()  # "Linux", "Darwin", "Windows"


def _is_wayland() -> bool:
    import os
    return bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "wayland"


# ---------------------------------------------------------------------------
# Desktop capture
# ---------------------------------------------------------------------------

def capture_desktop(mode: str, output: Path, delay_ms: int) -> None:
    if delay_ms:
        time.sleep(delay_ms / 1000)

    if OS == "Darwin":
        return _capture_macos(mode, output)
    if OS == "Windows":
        return _capture_windows(mode, output)
    return _capture_linux(mode, output)


def _capture_macos(mode: str, output: Path) -> None:
    flags = {"full": [], "window": ["-i", "-w"], "region": ["-i"]}[mode]
    subprocess.run(["screencapture", *flags, str(output)], check=True)
    if not output.exists():
        raise RuntimeError("screencapture produced no output (selection cancelled?)")


def _capture_windows(mode: str, output: Path) -> None:
    if mode != "full":
        # Interactive window/region selection has no scriptable Windows API
        # without extra deps; Pillow can't do it either. Best effort: full grab.
        print(f"Note: '{mode}' mode isn't scriptable on Windows, capturing full screen instead.",
              file=sys.stderr)
    from PIL import ImageGrab
    img = ImageGrab.grab()
    img.save(output)


def _find_linux_tool() -> tuple[str, str]:
    """Return (tool_name, backend) picking the best available capture tool."""
    if _is_wayland():
        for tool in ("spectacle", "grim"):
            if shutil.which(tool):
                return tool, "wayland"
    else:
        for tool in ("spectacle", "gnome-screenshot", "scrot", "maim", "import"):
            if shutil.which(tool):
                return tool, "x11"
    raise RuntimeError(
        "No screenshot tool found. Install one: spectacle, grim+slurp (Wayland), "
        "gnome-screenshot, scrot, maim, or ImageMagick's `import` (X11)."
    )


def _capture_linux(mode: str, output: Path) -> None:
    tool, backend = _find_linux_tool()

    if tool == "spectacle":
        flag = {"full": "-f", "window": "-a", "region": "-r"}[mode]
        subprocess.run(["spectacle", "-b", "-n", flag, "-o", str(output)], check=True, capture_output=True)
    elif tool == "grim":
        if mode == "region":
            if not shutil.which("slurp"):
                raise RuntimeError("region capture with grim needs slurp installed")
            geometry = subprocess.run(["slurp"], check=True, capture_output=True, text=True).stdout.strip()
            subprocess.run(["grim", "-g", geometry, str(output)], check=True)
        else:
            if mode == "window":
                print("Note: grim has no window mode, capturing full screen instead.", file=sys.stderr)
            subprocess.run(["grim", str(output)], check=True)
    elif tool == "gnome-screenshot":
        flag = {"full": [], "window": ["-w"], "region": ["-a"]}[mode]
        subprocess.run(["gnome-screenshot", *flag, "-f", str(output)], check=True)
    elif tool == "scrot":
        flag = {"full": [], "window": ["-u"], "region": ["-s"]}[mode]
        subprocess.run(["scrot", *flag, str(output)], check=True)
    elif tool == "maim":
        if mode == "window":
            win = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True).stdout.strip()
            subprocess.run(["maim", "-i", win, str(output)], check=True)
        else:
            flag = ["-s"] if mode == "region" else []
            subprocess.run(["maim", *flag, str(output)], check=True)
    elif tool == "import":
        target = "root" if mode == "full" else None
        cmd = ["import", str(output)] if target is None else ["import", "-window", target, str(output)]
        subprocess.run(cmd, check=True)

    if not output.exists():
        raise RuntimeError(f"{tool} produced no output (selection cancelled?)")


# ---------------------------------------------------------------------------
# Web capture (headless Chromium via CDP) -- minimal stdlib WebSocket client,
# adapted from claudeshot's cdp-screenshot.py approach.
# ---------------------------------------------------------------------------

class _SimpleWebSocket:
    def __init__(self, url: str):
        assert url.startswith("ws://")
        host_port, path = url[5:].split("/", 1)
        path = "/" + path
        host, _, port = host_port.partition(":")
        port = int(port) if port else 80

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect((host, port))

        key = base64.b64encode(random.randbytes(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(1024)
        if b"101" not in response:
            raise RuntimeError(f"WebSocket handshake failed: {response[:100]!r}")

    def send(self, message: str) -> None:
        payload = message.encode("utf-8")
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        mask = random.randbytes(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv(self) -> str | None:
        header = self._recv_exact(2)
        opcode = header[0] & 0x0F
        masked = (header[1] >> 7) & 1
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else None
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x01:
            return payload.decode("utf-8")
        if opcode == 0x08:
            return None
        return self.recv()

    def _recv_exact(self, n: int) -> bytes:
        data = bytearray()
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise RuntimeError("connection closed")
            data.extend(chunk)
        return bytes(data)

    def close(self) -> None:
        try:
            self.sock.sendall(b"\x88\x80" + random.randbytes(4))
        except OSError:
            pass
        self.sock.close()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _find_chromium() -> str:
    names = ["chromium-browser", "chromium", "google-chrome", "google-chrome-stable"]
    if OS == "Darwin":
        names = ["google-chrome", "chromium"]  # shutil.which covers PATH; .app bundles below
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    if OS == "Darwin":
        for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                   "/Applications/Chromium.app/Contents/MacOS/Chromium"):
            if Path(p).exists():
                return p
    if OS == "Windows":
        import os
        for p in (
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        ):
            expanded = os.path.expandvars(p)
            if Path(expanded).exists():
                return expanded
    raise RuntimeError("no Chromium/Chrome binary found")


def _launch_chromium(chromium: str, port: int, width: int, height: int, url: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            chromium,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            f"--remote-debugging-port={port}",
            f"--window-size={width},{height}",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_devtools(port: int) -> list[dict]:
    for _ in range(20):
        try:
            return json.loads(urllib.request.urlopen(f"http://localhost:{port}/json", timeout=5).read())
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("could not connect to Chromium DevTools")


def capture_web(url: str, output: Path, width: int, height: int, full_page: bool, dark: bool = False) -> None:
    chromium = _find_chromium()
    port = _find_free_port()
    proc = _launch_chromium(chromium, port, width, height, url)
    try:
        pages = _wait_for_devtools(port)
        ws_url = next((p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page"), None)
        if not ws_url:
            raise RuntimeError("no page target found")

        ws = _SimpleWebSocket(ws_url)
        msg_id = 0

        def call(method: str, params: dict | None = None) -> dict:
            nonlocal msg_id
            msg_id += 1
            this_id = msg_id
            ws.send(json.dumps({"id": this_id, "method": method, "params": params or {}}))
            while True:
                raw = ws.recv()
                if raw is None:
                    raise RuntimeError("connection closed mid-call")
                data = json.loads(raw)
                if data.get("id") == this_id:
                    if "error" in data:
                        raise RuntimeError(data["error"])
                    return data.get("result", {})

        time.sleep(0.5)  # let initial navigation settle

        if dark:
            call("Emulation.setEmulatedMedia",
                 {"features": [{"name": "prefers-color-scheme", "value": "dark"}]})
            time.sleep(0.2)

        if full_page:
            metrics = call("Page.getLayoutMetrics")
            content_height = int(metrics["contentSize"]["height"])
            call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": content_height, "deviceScaleFactor": 1, "mobile": False},
            )
            time.sleep(0.3)

        result = call(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
        )
        output.write_bytes(base64.b64decode(result["data"]))
        ws.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def capture_dom(url: str, output: Path) -> None:
    try:
        chromium = _find_chromium()
        result = subprocess.run(
            [chromium, "--headless=new", "--disable-gpu", "--no-sandbox", "--dump-dom", url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            output.write_text(result.stdout)
            return
    except (RuntimeError, subprocess.SubprocessError):
        pass
    # Fallback: raw HTML, no JS rendering
    with urllib.request.urlopen(url, timeout=15) as resp:
        output.write_bytes(resp.read())


# ---------------------------------------------------------------------------
# Post-processing (Pillow)
# ---------------------------------------------------------------------------

def resize_image(path: Path, width: int) -> None:
    _require_pillow()
    with Image.open(path) as img:
        ratio = width / img.width
        new_size = (width, max(1, round(img.height * ratio)))
        img.resize(new_size, Image.LANCZOS).save(path)


def convert_to_jpeg(path: Path) -> Path:
    _require_pillow()
    jpeg_path = path.with_suffix(".jpg")
    with Image.open(path) as img:
        img.convert("RGB").save(jpeg_path, "JPEG", quality=85)
    path.unlink()
    return jpeg_path


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

def copy_to_clipboard(path: Path) -> None:
    if OS == "Darwin":
        subprocess.run(
            ["osascript", "-e",
             f'set the clipboard to (read (POSIX file "{path}") as TIFF picture)'],
            check=True,
        )
        return
    if OS == "Windows":
        _copy_to_clipboard_windows(path)
        return
    # Linux
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    if _is_wayland() and shutil.which("wl-copy"):
        with open(path, "rb") as f:
            subprocess.run(["wl-copy", "-t", mime], stdin=f, check=True)
        return
    if shutil.which("xclip"):
        with open(path, "rb") as f:
            subprocess.run(["xclip", "-selection", "clipboard", "-t", mime, "-i"], stdin=f, check=True)
        return
    if shutil.which("xsel"):
        with open(path, "rb") as f:
            subprocess.run(["xsel", "--clipboard", "--input"], stdin=f, check=True)
        return
    raise RuntimeError("no clipboard tool found (wl-copy/xclip/xsel)")


def _copy_to_clipboard_windows(path: Path) -> None:
    """Write a DIB to the Windows clipboard via ctypes (stdlib only)."""
    import ctypes
    import io

    with Image.open(path) as img:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "BMP")
    dib = buf.getvalue()[14:]  # strip the 14-byte BITMAPFILEHEADER, keep the DIB

    CF_DIB = 8
    GMEM_MOVEABLE = 0x0002
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
    ptr = kernel32.GlobalLock(h_mem)
    ctypes.memmove(ptr, dib, len(dib))
    kernel32.GlobalUnlock(h_mem)

    user32.OpenClipboard(0)
    user32.EmptyClipboard()
    user32.SetClipboardData(CF_DIB, h_mem)
    user32.CloseClipboard()


# ---------------------------------------------------------------------------
# Session tracking (list / clear)
# ---------------------------------------------------------------------------

def _session_log() -> Path:
    return Path.cwd() / ".screenshots" / ".session.log"


def _track(path: Path) -> None:
    log = _session_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        f.write(f"{path}\n")
    lines = log.read_text().splitlines()
    if len(lines) > 1000:
        log.write_text("\n".join(lines[-500:]) + "\n")


def _safe_to_delete(path: Path) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and path.suffix in (".png", ".jpg", ".html", ".mp4", ".webm", ".gif", ".json")
        and path.parent == Path.cwd() / ".screenshots"
    )


def list_screenshots() -> int:
    log = _session_log()
    if not log.exists():
        print("No screenshots this session.")
        return 0
    for line in log.read_text().splitlines():
        p = Path(line)
        if p.exists():
            print(p)
    return 0


def clear_screenshots(confirm: bool) -> int:
    log = _session_log()
    if not log.exists():
        print("No screenshots to clear.")
        return 0
    paths = [Path(line) for line in log.read_text().splitlines()]
    safe = [p for p in paths if _safe_to_delete(p)]
    if not safe:
        log.unlink()
        print("No screenshots to clear.")
        return 0
    if confirm:
        print(f"Delete {len(safe)} screenshot(s)?")
        for p in safe:
            print(f"  {p}")
        if input("[y/N] ").strip().lower() != "y":
            print("Cancelled.")
            return 0
    for p in safe:
        if _safe_to_delete(p):
            p.unlink()
    log.unlink()
    print(f"Cleared {len(safe)} screenshot(s).")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["full", "window", "region"], default="full",
                    help="desktop capture mode (ignored if --web is given)")
    p.add_argument("--web", metavar="URL", help="screenshot a web page via headless Chromium")
    p.add_argument("--web-width", type=int, default=1280, help="Chromium viewport width")
    p.add_argument("--web-height", type=int, default=800, help="Chromium viewport height")
    p.add_argument("--mobile", action="store_true", help="mobile viewport (390x844)")
    p.add_argument("--tablet", action="store_true", help="tablet viewport (768x1024)")
    p.add_argument("--viewport-size", metavar="WxH", help="custom viewport, e.g. 375x667")
    p.add_argument("--viewport", action="store_true",
                    help="capture only the visible viewport instead of the full scrollable page")
    p.add_argument("--dark", action="store_true", help="emulate prefers-color-scheme: dark")
    p.add_argument("--dom", action="store_true", help="also save page HTML alongside a --web screenshot")
    p.add_argument("--delay", type=int, default=0, help="delay before desktop capture, seconds")
    p.add_argument("--output", type=Path, help="explicit output path")
    p.add_argument("--resize", type=int, metavar="WIDTH", help="resize to WIDTH px, keep aspect ratio")
    p.add_argument("--small", action="store_true", help="resize to 1280px width")
    p.add_argument("--tiny", action="store_true", help="resize to 640px width")
    p.add_argument("--jpeg", action="store_true", help="save as JPEG instead of PNG")
    p.add_argument("--clipboard", action="store_true", help="also copy result to clipboard")
    p.add_argument("--list", action="store_true", help="list this session's screenshots and exit")
    p.add_argument("--clear", action="store_true", help="delete this session's screenshots (asks first)")
    p.add_argument("--clear-yes", action="store_true", help="delete this session's screenshots, no prompt")
    p.add_argument("--record", choices=["term", "gui", "web", "desktop"],
                   help="record video/gif (output ext .mp4/.webm/.gif, default .mp4); web needs --web URL")
    p.add_argument("--steps", metavar="JSON|FILE", help="scripted steps for --record term/gui/web (see record.py)")
    p.add_argument("--seconds", type=float, default=5, help="--record desktop duration")
    p.add_argument("--fps", type=int, default=15)
    p.add_argument("--cols", type=int, help="--record term columns (default 80)")
    p.add_argument("--rows", type=int, help="--record term rows (default 20)")
    p.add_argument("--font", type=int, help="--record term font size (default 18)")
    p.add_argument("--format", choices=["16:9", "9:16"], help="--record: capture geometry for a video of this aspect (storyboard-video)")
    p.add_argument("--size", metavar="WxH", help="--record gui/web: window size (overrides --format)")
    p.add_argument("--keep-output", action="store_true", help="--record: keep typed text and shell output in the .json receipt")
    p.add_argument("--app", help='--record gui: command to run, e.g. "kcalc" (forced to X11 on a virtual display)')
    p.add_argument("--cwd", help="--record term/gui working directory")
    p.add_argument("--setup", help="--record term: shell snippet run before recording")
    p.add_argument("--gif", action="store_true", help="--record: write a .gif instead of .mp4")
    p.add_argument("--selftest", action="store_true", help="run self-check and exit")
    return p


def default_output(ext: str = "png") -> Path:
    d = Path.cwd() / ".screenshots"
    d.mkdir(exist_ok=True)
    return d / f"shot-{datetime.now():%Y%m%d-%H%M%S}.{ext}"


def _record(args) -> int:
    import record
    ext = ".gif" if args.gif else ".mp4"
    output = args.output or default_output(ext.lstrip("."))
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.record == "desktop":
        meta = record.record_desktop(output, args.seconds, args.fps)
    else:
        if not args.steps:
            raise SystemExit("--record term/gui/web needs --steps")
        steps = record.load_steps(args.steps)
        geo = record.GEOMETRY.get(args.format or "")
        kind = "gui" if args.record == "gui" else "web"
        if args.size:
            w, h = (int(v) for v in args.size.lower().split("x"))
        else:
            w, h = geo[kind] if geo else (args.web_width, args.web_height)
        keep = args.keep_output
        if args.record == "gui":
            if not args.app:
                raise SystemExit("--record gui needs --app")
            meta = record.record_gui(args.app, steps, output, w, h, args.fps, keep_output=keep, cwd=args.cwd)
        elif args.record == "web":
            if not args.web:
                raise SystemExit("--record web needs --web URL")
            meta = record.record_web(args.web, steps, output, w, h, args.fps, keep_output=keep, dark=args.dark)
        else:
            meta = record.record_term(
                steps, output, args.cols or (geo["cols"] if geo else 80), args.rows or (geo["rows"] if geo else 20),
                args.font or (geo["font"] if geo else 18), args.fps, cwd=args.cwd, setup=args.setup, keep_output=keep)
    _track(output)
    if output.with_suffix(".json").exists():
        _track(output.with_suffix(".json"))  # so --clear removes the receipt too
    print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    needs_pillow = args.selftest or not (args.list or args.clear or args.clear_yes or args.record)
    if needs_pillow and Image is None:  # list/clear/recording do not touch Pillow
        print(f"screencapture: {PILLOW_HINT}", file=sys.stderr)
        if PILLOW_ERROR:
            print(f"  ({PILLOW_ERROR})", file=sys.stderr)
        return 2
    if args.selftest:
        return _selftest()
    if args.list:
        return list_screenshots()
    if args.clear:
        return clear_screenshots(confirm=True)
    if args.clear_yes:
        return clear_screenshots(confirm=False)

    if args.record:
        return _record(args)

    width, height = args.web_width, args.web_height
    if args.mobile:
        width, height = VIEWPORTS["mobile"]
    elif args.tablet:
        width, height = VIEWPORTS["tablet"]
    elif args.viewport_size:
        w, h = args.viewport_size.split("x")
        width, height = int(w), int(h)

    output = args.output or default_output()
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.web:
        capture_web(args.web, output, width, height, full_page=not args.viewport, dark=args.dark)
    else:
        capture_desktop(args.mode, output, args.delay * 1000)

    presets_width = args.resize or (PRESETS["small"] if args.small else PRESETS["tiny"] if args.tiny else None)
    if presets_width:
        resize_image(output, presets_width)

    if args.jpeg:
        output = convert_to_jpeg(output)

    dom_output = None
    if args.dom and args.web:
        dom_output = output.with_suffix(".html")
        capture_dom(args.web, dom_output)

    if args.clipboard:
        copy_to_clipboard(output)

    _track(output)
    print(output)
    if dom_output:
        _track(dom_output)
        print(dom_output)
    return 0


def _selftest() -> int:
    """Exercise the non-trivial pieces: Pillow resize/format, CDP capture, DOM capture."""
    import tempfile

    _require_pillow()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        img_path = tmp / "test.png"
        Image.new("RGB", (400, 200), "red").save(img_path)
        resize_image(img_path, 200)
        with Image.open(img_path) as img:
            assert img.size == (200, 100), f"resize failed: got {img.size}"

        jpeg_path = convert_to_jpeg(img_path)
        assert jpeg_path.suffix == ".jpg" and jpeg_path.exists(), "jpeg conversion failed"
        assert not img_path.exists(), "original png should be removed after conversion"

        web_out = tmp / "web.png"
        capture_web("about:blank", web_out, width=800, height=600, full_page=True)
        assert web_out.exists() and web_out.stat().st_size > 0, "CDP capture produced no file"
        with Image.open(web_out) as img:
            assert img.width == 800, f"CDP capture width mismatch: got {img.width}"

        dom_out = tmp / "dom.html"
        capture_dom("about:blank", dom_out)
        assert dom_out.exists() and dom_out.stat().st_size > 0, "DOM capture produced no file"

    print("selftest OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
