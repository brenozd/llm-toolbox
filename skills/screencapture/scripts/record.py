"""Scripted recordings: `term` (real xterm on a virtual X display), `gui` (any app on a virtual X display), `web` (Playwright) and `desktop`
(the real screen, no input). Output by extension: .mp4, .webm or .gif.

Steps are JSON, shared by term and web:
  {"type":"type","text":"ls"}  {"type":"key","key":"Return"}  {"type":"click","x":10,"y":20,"button":1}
  {"type":"move","x":10,"y":20}  {"type":"scroll","dy":300}  {"type":"wait_for","text":"ok","timeout_s":8}
  {"type":"hold_s","s":1}   web only: {"type":"goto","url":...}, click/type/wait_for with "selector".
`key` is an xdotool keysym in term ("Return", "ctrl+c") and a Playwright key in web ("Enter", "Control+c").
"""

import json
import os
import platform
import random
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

STEP_TYPES = {"type", "key", "click", "move", "scroll", "wait_for", "hold_s", "goto"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
FORMATS = {".mp4", ".webm", ".gif"}


def _h264() -> list[str]:
    """libx264 where present; Fedora's ffmpeg only ships openh264, which wants a bitrate."""
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "libx264" in enc:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    return ["-c:v", "libopenh264", "-b:v", "6M"]


def load_steps(arg: str) -> list[dict]:
    """`arg` is a JSON file path or an inline JSON list."""
    p = Path(arg)
    steps = json.loads(p.read_text() if p.is_file() else arg)
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty JSON list")
    for i, s in enumerate(steps):
        ty = s.get("type") if isinstance(s, dict) else None
        if ty not in STEP_TYPES:
            raise ValueError(f"step {i}: type must be one of {sorted(STEP_TYPES)}")
        if ty == "type" and not s.get("text"):
            raise ValueError(f"step {i} (type): needs 'text'")
        if ty == "key" and not s.get("key"):
            raise ValueError(f"step {i} (key): needs 'key'")
        if ty == "goto" and not s.get("url"):
            raise ValueError(f"step {i} (goto): needs 'url'")
        if ty in ("click", "move") and not (("x" in s and "y" in s) or s.get("selector")):
            raise ValueError(f"step {i} ({ty}): needs x/y or selector")
        if ty == "wait_for" and not (s.get("text") or s.get("selector")):
            raise ValueError(f"step {i} (wait_for): needs text or selector")
    return steps


def check_tools(*tools: str) -> None:
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        hint = {"xdotool": "dnf install xdotool", "Xvfb": "dnf install xorg-x11-server-Xvfb",
                "xterm": "dnf install xterm", "script": "dnf install util-linux-script", "ffmpeg": "dnf install ffmpeg"}
        raise RuntimeError("missing: " + ", ".join(f"{m} ({hint.get(m, 'install it')})" for m in missing))


def finalize(src: Path, out: Path, fps: int = 15) -> None:
    """Re-encode a raw recording into the requested container (gif via a generated palette)."""
    ext = out.suffix.lower()
    if ext not in FORMATS:
        raise ValueError(f"output must end in one of {sorted(FORMATS)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if ext == ".gif":
        vf = f"fps={fps},split[a][b];[a]palettegen[p];[b][p]paletteuse"
        argv = ["-i", str(src), "-vf", vf, "-loop", "0"]
    elif ext == ".webm":
        argv = ["-i", str(src), "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0"]
    else:
        argv = ["-i", str(src), *_h264(), "-pix_fmt", "yuv420p",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart"]
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *argv, str(out)], capture_output=True, text=True)
    if r.returncode or not out.exists():
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[:300]}")


def _kill(p: subprocess.Popen | None) -> None:
    if p is None or p.poll() is not None:
        return
    try:
        os.killpg(p.pid, signal.SIGTERM)  # started with start_new_session
    except OSError:
        p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()


def _stop_ffmpeg(ff: subprocess.Popen) -> None:
    if ff.poll() is None:
        try:
            ff.stdin.write(b"q")  # graceful: ffmpeg writes the mp4 trailer
            ff.stdin.flush()
        except OSError:
            pass
        try:
            ff.wait(timeout=20)
        except subprocess.TimeoutExpired:
            _kill(ff)


def _until(pred, timeout: float, step: float = 0.1):
    end = time.monotonic() + timeout
    while True:
        v = pred()
        if v:
            return v
        if time.monotonic() >= end:
            return None
        time.sleep(step)


# ---------------------------------------------------------------------------
# Virtual X display + xdotool (shared by `term` and `gui`)
# ---------------------------------------------------------------------------

class XSession:
    """Xvfb on a free display (Xvfb picks it via -displayfd, so concurrent takes never collide)."""

    def __init__(self, w: int, h: int):
        r, wfd = os.pipe()
        self.proc = subprocess.Popen(
            ["Xvfb", "-displayfd", str(wfd), "-screen", "0", f"{w}x{h}x24", "-nolisten", "tcp"],
            pass_fds=[wfd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        os.close(wfd)
        with os.fdopen(r) as f:
            n = f.readline().strip()  # empty line = Xvfb died before it was ready
        if not n:
            _kill(self.proc)
            raise RuntimeError("Xvfb did not start")
        self.display = f":{n}"
        self.home = tempfile.mkdtemp(prefix="screencapture-home-")  # keeps host dotfiles out of the take
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home, "DISPLAY": self.display,
                    "TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PS1": "$ "}
        if os.environ.get("LD_LIBRARY_PATH"):  # a user-local xdotool (no root) needs its libxdo
            self.env["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH"]

    def xdo(self, *argv: str) -> str:
        """xdotool, failing loudly: a dropped keystroke silently desynchronises the take."""
        r = subprocess.run(["xdotool", *argv], env=self.env, capture_output=True, text=True, timeout=15)
        if r.returncode:
            raise RuntimeError(f"xdotool {' '.join(argv[:2])} failed: {r.stderr.strip()[:200]}")
        return r.stdout

    def window(self, title: str, timeout: float = 15) -> tuple[str, tuple[int, int, int, int]]:
        """Find *our* window by its unique anchored title; returns (id, (x, y, w, h)) and focuses it."""
        def find():
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", f"^{re.escape(title)}$"],
                               env=self.env, capture_output=True, text=True, timeout=10)
            return (r.stdout.split() or [None])[0]
        win = _until(find, timeout)
        if not win:
            raise RuntimeError(f"window {title!r} never appeared")
        self.xdo("windowfocus", "--sync", win)  # without a WM nothing sets the input focus
        g = dict(ln.split("=", 1) for ln in self.xdo("getwindowgeometry", "--shell", win).split())
        return win, (int(g["X"]), int(g["Y"]), int(g["WIDTH"]) // 2 * 2, int(g["HEIGHT"]) // 2 * 2)

    def start_ffmpeg(self, raw: Path, box: tuple[int, int, int, int], fps: int) -> subprocess.Popen:
        x, y, w, h = box
        return subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps), "-video_size", f"{w}x{h}",
             "-i", f"{self.display}+{x},{y}", *_h264(),
             "-pix_fmt", "yuv420p", str(raw)],
            env=self.env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run_steps(self, steps: list[dict], typer, wait_text=None, seed: int = 0, delay_ms: int = 60,
                  jitter_ms: int = 30) -> None:
        rng = random.Random(seed)
        for s in steps:
            ty = s["type"]
            if ty == "type":
                for ch in s["text"]:
                    self.xdo("type", "--clearmodifiers", "--delay", "0", "--", ch)
                    time.sleep(max(0.0, delay_ms + rng.randint(-jitter_ms, jitter_ms)) / 1000)
            elif ty == "key":
                self.xdo("key", "--clearmodifiers", s["key"])
            elif ty in ("click", "move"):
                if "x" not in s:
                    raise ValueError(f"{ty} on a virtual X display needs x/y (selectors are web-only)")
                self.xdo("mousemove", "--sync", str(int(s["x"])), str(int(s["y"])))
                if ty == "click":
                    self.xdo("click", str(s.get("button", 1)))
            elif ty == "scroll":  # buttons 4/5 are wheel up/down; one click per ~100 px
                for _ in range(max(1, abs(int(s.get("dy", 100))) // 100)):
                    self.xdo("click", "5" if s.get("dy", 100) > 0 else "4")
            elif ty == "wait_for":
                if wait_text is None:
                    raise ValueError("wait_for is not available for gui (no text stream): use hold_s")
                if not wait_text(s["text"], float(s.get("timeout_s", 8))):
                    raise RuntimeError(f"wait_for {s['text']!r} timed out: no half clip shipped")
            elif ty == "hold_s":
                time.sleep(max(0.0, float(s.get("s", 0.5))))
            else:
                raise ValueError(f"step type {ty!r} is not valid here")

    def close(self) -> None:
        _kill(self.proc)
        shutil.rmtree(self.home, ignore_errors=True)


def record_term(steps: list[dict], out: Path, cols: int = 80, rows: int = 20, font_size: int = 18, fps: int = 15,
                cwd: str | None = None, delay_ms: int = 60, jitter_ms: int = 30, seed: int = 0,
                tail_s: float = 1.2, setup: str | None = None) -> dict:
    """Xvfb -> xterm -> bash, keys via xdotool, grabbed with ffmpeg x11grab. The typing speed is staged;
    the output is the real shell running the real command."""
    check_tools("Xvfb", "xterm", "xdotool", "ffmpeg", "script")
    if any(s["type"] == "goto" for s in steps):
        raise ValueError("'goto' is a web step")
    work = Path(tempfile.mkdtemp(prefix="screencapture-"))
    log, raw = work / "pty.log", work / "raw.mp4"
    xs = XSession(1920, 1080)
    xt = ff = None
    try:
        rc = work / "rc"
        rc.write_text((setup or "") + "\nPS1='$ '\nclear\n")
        title = f"sc-{os.getpid()}-{int(time.time())}"
        xt = subprocess.Popen(
            ["xterm", "-fa", "DejaVu Sans Mono", "-fs", str(font_size), "+sb", "-bg", "#07080b", "-fg", "#e8ecf4",
             "-geometry", f"{cols}x{rows}+0+0", "-title", title, "-e", "script", "-q", "-f", "-c",
             f"exec bash --noprofile --rcfile {rc} -i", str(log)],
            cwd=cwd, env=xs.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        _, box = xs.window(title)
        off = 0

        def wait_text(needle: str, timeout_s: float) -> bool:
            nonlocal off

            def hit():
                nonlocal off
                chunk = log.read_bytes()[off:]
                if needle in ANSI.sub("", chunk.decode("utf-8", "replace")).replace("\r", ""):
                    off += len(chunk)
                    return True
            return bool(_until(hit, timeout_s, 0.05))

        time.sleep(0.5)  # let the prompt paint before the first frame
        ff = xs.start_ffmpeg(raw, box, fps)
        time.sleep(0.3)
        t0 = time.monotonic()
        xs.run_steps(steps, None, wait_text, seed, delay_ms, jitter_ms)
        time.sleep(tail_s)
        dur = time.monotonic() - t0
        _stop_ffmpeg(ff)
        ff = None
        finalize(raw, out, fps)
        output = ANSI.sub("", log.read_bytes().decode("utf-8", "replace")).replace("\r", "")
        meta = {"mode": "term", "video": str(out), "duration_s": round(dur, 2), "size": list(box[2:]),
                "seed": seed, "steps": steps, "output": output[-4000:]}
        out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        return meta
    finally:
        if ff:
            _stop_ffmpeg(ff)
        _kill(xt)
        xs.close()
        shutil.rmtree(work, ignore_errors=True)


def record_gui(app: str, steps: list[dict], out: Path, width: int = 1280, height: int = 720, fps: int = 15,
               cwd: str | None = None, delay_ms: int = 60, jitter_ms: int = 30, seed: int = 0,
               tail_s: float = 1.0, start_s: float = 1.5) -> dict:
    """Run a GUI app on a private Xvfb (forced to X11 even on a Wayland host), stretch its window over the
    whole screen at 0,0 (so click x/y are window coordinates), drive it with xdotool and grab it."""
    check_tools("Xvfb", "xdotool", "ffmpeg")
    if any(s["type"] in ("goto", "wait_for") for s in steps):
        raise ValueError("'goto' is a web step and 'wait_for' is term/web only")
    work = Path(tempfile.mkdtemp(prefix="screencapture-"))
    raw = work / "raw.mp4"
    xs = XSession(width, height)
    xs.env.update({"GDK_BACKEND": "x11", "QT_QPA_PLATFORM": "xcb", "SDL_VIDEODRIVER": "x11",
                   "MOZ_ENABLE_WAYLAND": "0", "ELECTRON_OZONE_PLATFORM_HINT": "x11"})
    xs.env["PATH"] = os.environ.get("PATH", xs.env["PATH"])
    proc = ff = None
    try:
        proc = subprocess.Popen(shlex.split(app), cwd=cwd, env=xs.env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        # the launcher may fork (pid != window owner), so take the first visible window on this private display
        def find():
            if proc.poll() not in (None, 0):
                raise RuntimeError(f"app exited early (rc={proc.returncode}): {proc.stderr.read()[-300:].decode(errors='replace')}")
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "."], env=xs.env,
                               capture_output=True, text=True, timeout=10)
            return (r.stdout.split() or [None])[-1]
        win = _until(find, 30)
        if not win:
            raise RuntimeError("the app opened no window on the virtual display")
        xs.xdo("windowmove", win, "0", "0")
        xs.xdo("windowsize", win, str(width), str(height))
        xs.xdo("windowfocus", win)
        time.sleep(start_s)
        ff = xs.start_ffmpeg(raw, (0, 0, width // 2 * 2, height // 2 * 2), fps)
        time.sleep(0.3)
        t0 = time.monotonic()
        xs.run_steps(steps, None, None, seed, delay_ms, jitter_ms)
        time.sleep(tail_s)
        dur = time.monotonic() - t0
        _stop_ffmpeg(ff)
        ff = None
        finalize(raw, out, fps)
        meta = {"mode": "gui", "video": str(out), "app": app, "duration_s": round(dur, 2),
                "size": [width, height], "seed": seed, "steps": steps}
        out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        return meta
    finally:
        if ff:
            _stop_ffmpeg(ff)
        _kill(proc)
        xs.close()
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Web (Playwright). It records the page without a cursor, so one is drawn with an injected overlay.
# ---------------------------------------------------------------------------

CURSOR_JS = """(() => {
 const add = () => { if (document.getElementById('__sc_cursor')) return;
  const c = document.createElement('div'); c.id = '__sc_cursor';
  // arrow tip is the SVG origin, so the tip lands exactly on the pointer coordinates
  c.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" style="display:block;filter:drop-shadow(1px 2px 2px rgba(0,0,0,.45))">' +
   '<path d="M2 1.5v18l4.8-4.3 3.2 7.2 3-1.4-3.2-7H17z" fill="#000" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  c.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;left:-50px;top:-50px;transform-origin:2px 1.5px;transition:transform .08s';
  document.documentElement.appendChild(c);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px' }, true);
  addEventListener('mousedown', e => { c.style.transform = 'scale(.8)';
   const r = document.createElement('div');  // click ripple
   r.style.cssText = 'position:fixed;z-index:2147483646;pointer-events:none;width:28px;height:28px;margin:-14px 0 0 -14px;border-radius:50%;' +
    'border:2px solid rgba(22,81,255,.8);left:' + e.clientX + 'px;top:' + e.clientY + 'px;transition:transform .4s,opacity .4s';
   document.documentElement.appendChild(r);
   requestAnimationFrame(() => { r.style.transform = 'scale(2)'; r.style.opacity = '0' }); setTimeout(() => r.remove(), 450); }, true);
  addEventListener('mouseup', () => { c.style.transform = '' }, true); };
 document.readyState === 'loading' ? addEventListener('DOMContentLoaded', add) : add(); })()"""


def _launch(p):
    try:
        return p.chromium.launch()
    except Exception:  # no bundled browser: fall back to a system Chromium
        for name in ("chromium", "chromium-browser", "google-chrome"):
            exe = shutil.which(name)
            if exe:
                return p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        raise RuntimeError("no Chromium: run `playwright install chromium` or install chromium/google-chrome")


def record_web(url: str, steps: list[dict], out: Path, width: int = 1280, height: int = 720, fps: int = 15,
               dark: bool = False, delay_ms: int = 60, tail_s: float = 1.0) -> dict:
    from playwright.sync_api import sync_playwright  # lazy: only this mode needs it
    work = Path(tempfile.mkdtemp(prefix="screencapture-"))
    try:
        with sync_playwright() as p:
            br = _launch(p)
            ctx = br.new_context(viewport={"width": width, "height": height},
                                 record_video_dir=str(work), record_video_size={"width": width, "height": height},
                                 color_scheme="dark" if dark else "light")
            ctx.add_init_script(CURSOR_JS)
            pg = ctx.new_page()
            pg.goto(url)
            pos = [width // 2, height // 2]

            def target(s):
                if s.get("selector"):
                    b = pg.locator(s["selector"]).first.bounding_box()
                    if not b:
                        raise RuntimeError(f"selector {s['selector']!r} has no box")
                    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
                return float(s["x"]), float(s["y"])

            def glide(x, y):  # a visible, human-paced move instead of a teleport
                pg.mouse.move(x, y, steps=18)
                pos[:] = [x, y]

            for s in steps:
                ty = s["type"]
                if ty == "goto":
                    pg.goto(s["url"])
                elif ty in ("click", "move"):
                    glide(*target(s))
                    if ty == "click":
                        pg.mouse.click(*pos, button={1: "left", 2: "middle", 3: "right"}[int(s.get("button", 1))])
                elif ty == "type":
                    if s.get("selector"):
                        glide(*target(s))
                        pg.mouse.click(*pos)
                    pg.keyboard.type(s["text"], delay=delay_ms)
                elif ty == "key":
                    pg.keyboard.press(s["key"])
                elif ty == "scroll":
                    pg.mouse.wheel(0, float(s.get("dy", 300)))
                    pg.wait_for_timeout(400)
                elif ty == "wait_for":
                    t = int(float(s.get("timeout_s", 8)) * 1000)
                    (pg.locator(s["selector"]).first.wait_for(timeout=t) if s.get("selector")
                     else pg.get_by_text(s["text"]).first.wait_for(timeout=t))
                elif ty == "hold_s":
                    pg.wait_for_timeout(int(float(s.get("s", 0.5)) * 1000))
            pg.wait_for_timeout(int(tail_s * 1000))
            vid = pg.video
            ctx.close()  # flushes the webm
            raw = Path(vid.path())
            br.close()
        finalize(raw, out, fps)
        meta = {"mode": "web", "video": str(out), "url": url, "size": [width, height], "steps": steps}
        out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        return meta
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Real desktop: recording only, no input.
# ---------------------------------------------------------------------------

def record_desktop(out: Path, seconds: float, fps: int = 15) -> dict:
    """Backend by session: spectacle (KDE) / wf-recorder (wlroots) on Wayland, x11grab on X11,
    avfoundation on macOS, gdigrab on Windows."""
    system = platform.system()
    work = Path(tempfile.mkdtemp(prefix="screencapture-"))
    raw = work / "raw.mp4"
    try:
        check_tools("ffmpeg")
        if system == "Darwin":
            argv = ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-framerate", str(fps), "-i", "1:none"]
        elif system == "Windows":
            argv = ["ffmpeg", "-y", "-loglevel", "error", "-f", "gdigrab", "-framerate", str(fps), "-i", "desktop"]
        elif os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            if shutil.which("wf-recorder"):
                argv = ["wf-recorder", "-f", str(raw)]
            elif shutil.which("spectacle"):
                argv = ["spectacle", "-b", "-n", "-R", "s", "-o", str(raw)]
            else:
                raise RuntimeError("Wayland recording needs wf-recorder (wlroots) or spectacle (KDE)")
            p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(seconds)
            os.killpg(p.pid, signal.SIGINT)  # both finish the file on SIGINT
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                _kill(p)
            argv = None
        else:
            argv = ["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps),
                    "-i", os.environ.get("DISPLAY", ":0")]
        if argv:
            subprocess.run([*argv, "-t", str(seconds), "-pix_fmt", "yuv420p", str(raw)], check=True,
                           capture_output=True, timeout=seconds + 60)
        if not raw.exists() or raw.stat().st_size < 1024:
            raise RuntimeError("the recorder produced no video (permission dialog dismissed?)")
        finalize(raw, out, fps)
        return {"mode": "desktop", "video": str(out), "duration_s": seconds}
    finally:
        shutil.rmtree(work, ignore_errors=True)
