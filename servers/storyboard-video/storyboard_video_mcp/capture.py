from __future__ import annotations

import json
import os
import random
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from . import config, spec as S
from .render import ARGS, _encoder
from .safety import safe_path

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
BAD = {"status": "error"}


def _cap_dir() -> tuple[str, "os.PathLike"]:
    cid = uuid.uuid4().hex[:8]
    d = config.WORK / "captures" / cid
    d.mkdir(parents=True, exist_ok=True)
    return cid, d


def _meta(d, **kw) -> None:
    """Record the geometry a capture was taken at: spec.recaptures() reads it back to tell which
    captures a different aspect has to redo."""
    (d / "capture.json").write_text(json.dumps(kw, indent=1))


def _need_exec():
    if not config.ALLOW_EXEC:
        raise PermissionError("exec tools are disabled: the operator must start the container with STORYBOARD_ALLOW_EXEC=1 "
                              "(use the storyboard-video-exec plugin entry)")


def _clean_env(display: str | None = None) -> dict:
    home = tempfile.mkdtemp(prefix="storyboard-home-")  # empty HOME so repo code cannot read user dotfiles
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "TERM": "dumb", "LANG": "C.UTF-8"}
    if display:
        env["DISPLAY"] = display
    return env


FONT = "DejaVu Sans Mono"
STEP_TYPES = {"type", "key", "wait_for", "hold_s"}


class _StepTimeout(RuntimeError):
    """A wait_for step ran out of time: the take is aborted instead of shipping half a clip."""


def _xenv(display: str, path_extra: str | None = None) -> dict:
    """Clean env for one X session: no host dotfiles, but a real terminal and a '$ ' prompt.
    `path_extra` (the session cwd) is appended to PATH so the project's own binaries run by name."""
    env = {**_clean_env(display), "TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PS1": "$ "}
    if path_extra:
        env["PATH"] += os.pathsep + path_extra
    return env


def _run(env: dict, argv: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def _until(pred, timeout: float, step: float = 0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v is not None:
            return v
        time.sleep(step)
    return None


def _settle_prompt(log: Path, timeout: float = 1.5, paint: float = 0.2) -> float:
    """Wait for the shell to have printed its prompt (the pty log gets bytes) instead of sleeping a
    fixed 0.8 s: a loaded box paints late and a fast one no longer wastes the wait. The `paint`
    sleep after the bytes land covers the cells xterm has not drawn yet. Returns the seconds waited.
    Not `_until`: its predicate must return non-None to keep polling, and a False returns at once."""
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        try:
            if log.exists() and log.stat().st_size:
                break
        except OSError:
            pass
        time.sleep(0.05)
    time.sleep(paint)
    return time.monotonic() - t


LOCKDIR = Path("/tmp")  # where X and our own display claims live


class _XdoError(RuntimeError):
    """An xdotool call failed: abort the take instead of shipping keys we did not send."""


def _display_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _claim_display() -> tuple[str, Path]:
    """Claim an X display atomically: O_EXCL on our own lock file, so two concurrent sessions can
    never both get :90 (the loser's Xvfb dies but xdotool would still reach the winner's server).
    Returns the display and the lock to release in the caller's finally."""
    for n in range(90, 600):
        lock = LOCKDIR / f".storyboard-x{n}.lock"
        if (LOCKDIR / f".X{n}-lock").exists():
            continue
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:  # a crashed take left it behind: take it over instead of leaking the display
                pid = lock.read_text()
                # empty = the owner created it but has not written its pid yet: not stale
                if pid and not _display_alive(int(pid)):
                    lock.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
            continue
        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        return f":{n}", lock
    raise RuntimeError("no free X display")


def _win_search(title: str) -> list[str]:
    """Find *our* xterm by its unique, anchored title -- a bare --class xterm search would hand
    back another take's window and type into its shell. (`--name` must precede anything else:
    xdotool rejects `--class ... --name ...` with "Unknown command".)"""
    return ["xdotool", "search", "--onlyvisible", "--name", f"^{re.escape(title)}$"]


def _xdo(env: dict, argv: list[str], what: str) -> str:
    """Run an xdotool call and fail loudly: a dropped keystroke silently desynchronises the take."""
    r = _run(env, ["xdotool", *argv], 10)
    if r.returncode != 0:
        raise _XdoError(f"xdotool {what} failed (rc={r.returncode}): {r.stderr.strip()[:200]}")
    return r.stdout


def _type_text(env: dict, text: str, delay_ms: int, jitter_ms: int, rng: random.Random) -> None:
    """Type char by char (a human-looking, evenly paced burst) and check every keystroke."""
    for ch in text:
        _xdo(env, ["type", "--clearmodifiers", "--delay", "0", "--", ch], f"type {ch!r}")
        time.sleep(max(0.0, delay_ms + rng.randint(-jitter_ms, jitter_ms)) / 1000)


def _kill(p) -> None:
    if p is None or p.poll() is not None:
        return
    try:
        if os.getpgid(p.pid) == p.pid:  # started with start_new_session: take the whole group with us
            os.killpg(p.pid, signal.SIGTERM)
        else:
            p.terminate()
    except (OSError, ProcessLookupError):
        p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()


def _xvfb(env: dict, disp: str, w: int, h: int) -> subprocess.Popen:
    p = subprocess.Popen(["Xvfb", disp, "-screen", "0", f"{w}x{h}x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if shutil.which("xdpyinfo"):
        ok = _until(lambda: True if _run(env, ["xdpyinfo"], 5).returncode == 0 else None, 15)
    else:
        time.sleep(1.0)
        ok = True
    if not ok:
        _kill(p)
        raise RuntimeError(f"Xvfb {disp} never came up")
    return p


def _xterm(env: dict, wd, cols: int, rows: int, font_size: int, title: str, log: Path, rc: Path):
    """Real xterm (no scrollbar, no WM) running bash on a pty that script(1) tees to `log`.
    The caller passes a unique title, so the window we find is always ours."""
    argv = ["xterm", "-fa", FONT, "-fs", str(font_size), "+sb", "-bg", "#07080b", "-fg", "#e8ecf4", "-cr", "#4cc2ff",
            "-geometry", f"{cols}x{rows}+0+0", "-title", title, "-e", "script", "-q", "-f", "-c",
            f"exec bash --rcfile {rc} -i", str(log)]
    p = subprocess.Popen(argv, cwd=wd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    def find():
        r = _run(env, _win_search(title), 10)
        if r.returncode not in (0, 1):  # 1 = no such window yet
            raise _XdoError(f"xdotool search failed (rc={r.returncode}): {r.stderr.strip()[:200]}")
        return (r.stdout.split() or [None])[0]
    try:
        win = _until(find, 15)
    except _XdoError:
        _kill(p)
        raise
    if not win:
        _kill(p)
        raise RuntimeError("the xterm window never appeared (a stale Xvfb or a missing CAP_SETGID breaks this)")
    _xdo(env, ["windowfocus", "--sync", win], "windowfocus")  # without a WM nothing sets the input focus
    geo = dict(ln.split("=", 1) for ln in _xdo(env, ["getwindowgeometry", "--shell", win], "getwindowgeometry").split())
    return p, win, (int(geo["X"]), int(geo["Y"]), int(geo["WIDTH"]), int(geo["HEIGHT"]))


def _norm_steps(steps: list[dict]) -> list[dict]:
    """Validate session steps, filling defaults. Unknown/incomplete steps are a hard error."""
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    out = []
    for i, s in enumerate(steps):
        ty = s.get("type") if isinstance(s, dict) else None
        if ty not in STEP_TYPES:
            raise ValueError(f"step {i}: type must be one of {sorted(STEP_TYPES)}")
        if ty in ("type", "wait_for"):
            if not isinstance(s.get("text"), str) or not s["text"]:
                raise ValueError(f"step {i} ({ty}): needs a non-empty 'text'")
            out.append({"type": ty, "text": s["text"], **({"timeout_s": float(s.get("timeout_s", 8))} if ty == "wait_for" else {})})
        elif ty == "key":
            if not isinstance(s.get("key"), str) or not s["key"]:
                raise ValueError(f"step {i} (key): needs an xdotool keysym like 'Return' or 'ctrl+c'")
            out.append({"type": "key", "key": s["key"]})
        else:
            try:
                secs = float(s.get("s", 0.5))
            except (TypeError, ValueError):
                raise ValueError(f"step {i} (hold_s): 's' must be a number") from None
            out.append({"type": "hold_s", "s": max(0.0, secs)})
    return out


def _pty(raw: bytes) -> str:
    return ANSI.sub("", raw.decode("utf-8", "replace")).replace("\r", "")


def _tail(log: Path, lines: int = 20, off: int = 0) -> str:
    """The last `lines` non-empty pty lines from byte `off`: off=where the recording started, so the
    `setup` output (and the `clear`) stay out of the receipt exactly as they stay off the screen."""
    try:
        txt = _pty(log.read_bytes()[off:][-65536:])
    except OSError:
        return ""
    keep = [ln for ln in txt.splitlines() if ln.strip() and not ln.startswith("Script ")]  # script(1) header/footer
    return "\n".join(keep[-lines:])


def _wait_text(log: Path, needle: str, timeout_s: float, off: int) -> int | None:
    """Poll the pty log from byte `off` for `needle`; returns the new offset to search from, or None."""
    def hit():
        try:
            with log.open("rb") as f:
                f.seek(off)
                chunk = f.read(262144)
        except OSError:
            return None
        return off + len(chunk) if needle in _pty(chunk) else None
    return _until(hit, timeout_s, 0.05)


def _stop_ffmpeg(ff) -> None:
    if ff is None or ff.poll() is not None:
        return
    try:
        ff.stdin.write(b"q")  # graceful: ffmpeg writes the mp4 trailer
        ff.stdin.flush()
    except OSError:
        pass
    try:
        ff.wait(timeout=20)
    except subprocess.TimeoutExpired:
        _kill(ff)


def _focus_of(pg, selector: str, vp: dict) -> dict | None:
    """Where the selector sits in the shot, as 0..1 fractions of the viewport.

    The element is scrolled into view first (an off-screen box measures outside the frame) and the box
    is clamped into the viewport, so `focus` can never point at a region the capture does not have."""
    loc = pg.locator(selector).first
    try:
        loc.scroll_into_view_if_needed(timeout=3000)
    except Exception:  # a fixed/sticky element is already in view: nothing to scroll
        pass
    try:
        box = loc.bounding_box(timeout=3000)  # bounded: a selector that never matches must not eat 30 s
    except Exception:  # Playwright's TimeoutError is not a RuntimeError, so it would escape the caller
        return None
    if not box:
        return None
    w, h = float(vp["width"]), float(vp["height"])
    x = min(max(box["x"] / w, 0.0), 1.0)
    y = min(max(box["y"] / h, 0.0), 1.0)
    return {"x": round(x, 4), "y": round(y, 4),
            "w": round(max(0.0, min(1.0 - x, box["width"] / w)), 4),
            "h": round(max(0.0, min(1.0 - y, box["height"] / h)), 4)}


SHOT_PATH_PREFIXES = ("/work", "/repo", "/tmp")  # container paths a caller mistook for URL paths
SHOT_PATH_EXTS = (".png", ".jpg", ".jpeg")  # an output image is never a page to navigate to
SETTLE_MAX_MS = 10000
WAIT_FOR_TIMEOUT_MS = 10000


def _goto_path(s: dict):
    """The page a shot navigates to before its screenshot: `goto_path` is the name, `path` is the old
    spelling of the same field and stays accepted so existing callers keep working."""
    v = s.get("goto_path") or s.get("path")
    return v if v not in (None, "") else None


def _goto_problem(gp) -> str | None:
    """Why `gp` cannot be a page to open, or None. The field used to be called `path`, so callers passed
    the PNG they wanted -- silently navigating to a file that does not exist. Reject those, and the
    container paths a caller confuses with a URL path, with a message that names the real PNG field."""
    if not isinstance(gp, str):
        return f"goto_path must be a string URL path, got {type(gp).__name__}"
    low = gp.strip().lower()
    if low.endswith(SHOT_PATH_EXTS):
        return (f"goto_path {gp!r} looks like an output image: goto_path is the URL path to navigate to "
                f"(e.g. '/dashboard'); the tool picks the PNG and returns it as shots[].path")
    for p in SHOT_PATH_PREFIXES:
        if low == p or low.startswith(p + "/"):
            return (f"goto_path {gp!r} is a container path, not a URL path: pass the page to open "
                    f"(e.g. '/dashboard'); the tool picks the PNG and returns it as shots[].path")
    return None


def capture_web(url: str, shots: list[dict], viewport: dict | None = None, aspect: str = "16:9",
                device_scale_factor: float | None = None) -> dict:
    """Screenshot pages of a local web app.

    url is the page opened first; each shot is {id, goto_path?, selector?, hide?, wait_for?, settle_ms?}:
    `goto_path` is the *URL path* of the page the shot navigates to (e.g. '/dashboard'), never a file
    (the old name `path` is still accepted as an alias); `wait_for` is a CSS selector waited for as
    visible (10 s) -- a selector that never appears records `wait_missing` in the shot instead of
    failing the call; `settle_ms` (0..10000) is extra time to let the page paint after navigating.
    Pages are loaded with `load`, never `networkidle`: an SSE page never reaches it. The PNG the tool
    writes is returned as shots[].path."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or u.hostname not in config.WEB_HOSTS:
        return {**BAD, "message": f"host not allowed ({u.hostname}); allowed: {sorted(config.WEB_HOSTS)}"}
    if not isinstance(shots, list) or not shots:
        return {**BAD, "message": "shots must be a non-empty list of objects, each with an 'id'"}
    for i, s in enumerate(shots):
        if not isinstance(s, dict):
            return {**BAD, "message": f"shots[{i}] must be an object, got {type(s).__name__}"}
        if not isinstance(s.get("id"), str) or not s["id"].strip():
            return {**BAD, "message": f"shots[{i}]: 'id' must be a non-empty string (got {s.get('id')!r}); "
                                   f"it names the shot and its PNG"}
    f = S.fmt(aspect)
    vp = viewport or dict(f["viewport"])
    dsf = device_scale_factor or f["device_scale_factor"]
    cid, d = _cap_dir()
    _meta(d, tool="capture_web", aspect=aspect, viewport=vp, device_scale_factor=dsf)
    out = []

    def gate(route):
        h = urlparse(route.request.url)
        ok = route.request.url.startswith(("data:", "about:")) or h.hostname in config.WEB_HOSTS
        route.continue_() if ok else route.abort()

    with sync_playwright() as p:
        br = p.chromium.launch(args=ARGS, executable_path=config.chromium())
        ctx = br.new_context(viewport=vp, device_scale_factor=dsf)
        ctx.route("**/*", gate)
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="load", timeout=20000)
        except Exception as e:  # a slow/blocked page is a finding, not a traceback out of the tool
            return {**BAD, "capture_id": cid, "message": f"could not load {url}: {type(e).__name__}: {e}"}
        for s in shots:
            sid = s["id"]
            gp = _goto_path(s)
            problem = _goto_problem(gp) if gp is not None else None
            if problem:
                out.append({"id": sid, "path": None, "focus": None, "message": problem})
                continue
            settle = s.get("settle_ms")
            if settle is not None and (isinstance(settle, bool) or not isinstance(settle, int)
                                       or not 0 <= settle <= SETTLE_MAX_MS):
                out.append({"id": sid, "path": None, "focus": None,
                            "message": f"settle_ms must be an integer 0..{SETTLE_MAX_MS}, got {settle!r}"})
                continue
            if gp:
                try:
                    pg.goto(urlparse(url)._replace(path=gp).geturl(), wait_until="load", timeout=20000)
                except Exception as e:  # one bad page must not lose the shots that already worked
                    out.append({"id": sid, "goto_path": gp, "path": None, "focus": None,
                                "message": f"could not load {gp}: {type(e).__name__}: {e}"})
                    continue
            for sel in s.get("hide", []):  # after the navigation: a new page drops earlier styles
                pg.add_style_tag(content=f"{sel}{{filter:blur(14px)!important}}")
            wait_missing = None
            if s.get("wait_for"):
                try:  # a page fed by SSE may never settle, so this is a bounded wait, not a gate
                    pg.wait_for_selector(str(s["wait_for"]), state="visible", timeout=WAIT_FOR_TIMEOUT_MS)
                except Exception:  # never appeared: a finding on the shot, the picture is still taken
                    wait_missing = str(s["wait_for"])
            if settle:  # after the navigation and the wait: time for the last paint to land
                pg.wait_for_timeout(settle)
            # measured *before* the shot: _focus_of scrolls the element into view, so a box taken
            # afterwards described pixels the PNG does not have (silent wrong zoom)
            focus = _focus_of(pg, s["selector"], vp) if s.get("selector") else None
            path = d / f"{sid}.png"
            pg.screenshot(path=str(path))
            shot = {"id": sid, "path": str(path), "focus": focus}
            if gp:
                shot["goto_path"] = gp  # which page this PNG is of, in the field's own name
            if s.get("selector") and focus is None:
                shot["selector_missing"] = s["selector"]  # rendered without a zoom, and the caller knows
            if wait_missing:
                shot["wait_missing"] = wait_missing  # the page painted late: a finding, not a lost take
            out.append(shot)
        br.close()
    return {"status": "ok", "capture_id": cid, "aspect": aspect, "viewport": vp, "shots": out}


def capture_terminal(command: str, cwd: str | None = None, timeout: int = 20, max_lines: int = 16,
                    cols: int | None = None, aspect: str = "16:9", crop_empty: bool = False) -> dict:
    """Run a command and keep its output as terminal lines (`max_lines` including the `$ command` line).

    `crop_empty` (opt-in, default False) drops the blank lines at the end of the output, so a scene
    does not render empty rows under the last line; lines in the middle are kept."""
    _need_exec()
    wd = safe_path(cwd or config.REPO)
    cols = cols or S.fmt(aspect)["max_cols"]
    cid, d = _cap_dir()
    _meta(d, tool="capture_terminal", aspect=aspect, cols=cols, max_lines=max_lines)
    try:
        # stderr merged into the same pipe: two pipes concatenated put every stderr line after all of
        # stdout, so an interleaved traceback arrived out of order
        r = subprocess.run(["bash", "-c", command], cwd=wd, env=_clean_env(), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        raw, code = r.stdout, r.returncode
    except subprocess.TimeoutExpired as e:
        out = e.output  # the merged stream: e.stdout when stderr=STDOUT
        raw = out.decode(errors="replace") if isinstance(out, bytes) else (out or "")
        code = -1
    body = [ln[:cols] for ln in ANSI.sub("", raw).replace("\r", "").splitlines()]
    if crop_empty:
        while body and not body[-1].strip():
            body.pop()
    shown = body[:max_lines - 1]
    lines = ["$ " + command[:cols - 2]] + shown
    (d / "lines.json").write_text(json.dumps(lines))
    (d / "terminal.txt").write_text("\n".join(lines))
    return {"status": "ok" if code == 0 else "warn", "capture_id": cid, "exit_code": code, "lines": lines,
            "truncated": len(body) > len(shown), "timed_out": code == -1}


def _crop_empty_rows(video: Path, w: int, h: int, rows: int, used: int) -> tuple[int, int] | None:
    """Re-encode `video` down to the rows the take actually used: the empty ones under the last line
    are dead space in the frame (and they shrink the text when the clip is scaled to fill it).
    Returns the new (w, h), or None when there is nothing to crop or the re-encode failed."""
    used = max(1, min(used, rows))
    if used >= rows or w <= 1 or h <= 1:
        return None
    ch = max(2, int(round(h * used / rows)) & ~1)  # yuv420p wants an even height
    tmp = video.with_suffix(".crop.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", f"crop={w}:{ch}:0:0",
                        *_encoder("18"), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)],
                       capture_output=True, timeout=180)
    if r.returncode or not tmp.exists() or tmp.stat().st_size < 1024:
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(video)
    return w, ch


def capture_terminal_session(steps: list[dict], cols: int | None = None, rows: int | None = None, delay_ms: int = 60,
                             jitter_ms: int = 30, seed: int = 0, fps: int = 15, cwd: str | None = None,
                             tail_s: float = 1.2, max_s: float = 120.0, title: str = "terminal",
                             font_size: int | None = None, aspect: str = "16:9", setup: str | None = None,
                             crop_empty: bool = False) -> dict:
    """Record a real terminal session: Xvfb -> xterm -> bash, keys via xdotool, grabbed with x11grab.

    steps: [{"type":"type","text":"cmd"}, {"type":"key","key":"Return"},
            {"type":"wait_for","text":"ok","timeout_s":8}, {"type":"hold_s","s":1.0}]
    The keystroke *speed* is staged (delay_ms + seeded jitter); what appears on screen is the
    real shell echoing and really running the command. wait_for reads the pty log from the point
    the previous step left off, so a timeout fails the whole take instead of shipping a half clip.
    cols/rows/font_size default to the format's geometry: 80x16 at font 22 for 16:9, a grid whose aspect
    matches the content box so the window fills the frame width instead of a small stamp of unreadable
    text (44x28 at 15 for 9:16). Pass rows = printed lines + 1 to size the window to the run.
    `crop_empty` (opt-in, default False) re-encodes the take down to the rows that carry text, so a
    short run in a tall window does not sit on half a screen of empty rows.
    """
    _need_exec()
    if setup is not None and not isinstance(setup, str):
        raise ValueError("setup must be one shell snippet (a string), e.g. 'cd /tmp/demo\nexport PATH=/repo/bin:$PATH'")
    f = S.fmt(aspect)
    cols, rows = cols or f["cols"], rows or f["rows"]
    font_size = font_size or f["font"]
    st = _norm_steps(steps)
    missing = [n for n in ("Xvfb", "xterm", "xdotool", "ffmpeg") if not shutil.which(n)]
    if missing:
        return {**BAD, "message": f"missing for a terminal session: {missing} (see the Dockerfile)"}
    wd = safe_path(cwd or config.REPO)
    cid, d = _cap_dir()
    mp4, log, poster, sess = d / "session.mp4", d / "pty.log", d / "poster.png", d / "session.json"
    rc = d / "rc"
    # explicit prompt: an exported PS1 is not reliable. `setup` (PATH, cd, aliases) runs before the grab so the
    # viewer sees `mint_loader ./leak`, not container paths; `clear` hides anything it printed. It runs in the
    # real take only: the measuring take below must not compile twice or append to the same file twice.
    base_rc = "PS1='$ '\nunset PROMPT_COMMAND\n"
    rc.write_text(base_rc)
    rng = random.Random(seed)
    disp, claim = _claim_display()
    env = _xenv(disp, str(wd))
    win_title = f"{title} {cid}"  # unique per take: the search below can only find our own window
    xv = term = ff = None
    try:
        # 1) throwaway take on an oversized screen solely to measure the window the font gives us
        xv = _xvfb(env, disp, max(1600, cols * 24), max(1000, rows * 48))
        term, _, (_, _, w, h) = _xterm(env, wd, cols, rows, font_size, win_title, log, rc)
        _kill(term)
        _kill(xv)
        # 2) real take: the X screen is sized to that window, so the grab is exactly the terminal
        log.unlink(missing_ok=True)
        if setup:
            rc.write_text(base_rc + f"{setup}\nclear\n")  # once, and before the grab starts
        xv = _xvfb(env, disp, w + 4, h + 4)
        term, _, (x, y, w, h) = _xterm(env, wd, cols, rows, font_size, win_title, log, rc)
        ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps),
                               "-draw_mouse", "0", "-video_size", f"{w}x{h}", "-i", f"{disp}+{x},{y}", *_encoder("18"),
                               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)],
                              stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _settle_prompt(log)  # the prompt is on screen before the first keystroke, without a fixed sleep
        if ff.poll() is not None:
            return {**BAD, "capture_id": cid, "message": "ffmpeg x11grab exited immediately"}
        mark = rec = log.stat().st_size if log.exists() else 0  # mark: wait_for only looks at output from here
        # on; rec stays put, so the receipt is exactly what the video shows (setup output included in neither)
        t0 = time.monotonic()
        for i, s in enumerate(st):
            if time.monotonic() - t0 > max_s:
                raise _StepTimeout(f"step {i}: session exceeded max_s={max_s}")
            if s["type"] == "type":
                _type_text(env, s["text"], delay_ms, jitter_ms, rng)
            elif s["type"] == "key":
                _xdo(env, ["key", "--clearmodifiers", s["key"]], f"key {s['key']!r}")
            elif s["type"] == "wait_for":
                found = _wait_text(log, s["text"], s["timeout_s"], mark)
                if found is None:
                    raise _StepTimeout(f"step {i}: wait_for {s['text'][:40]!r} timed out after {s['timeout_s']}s")
                mark = found
            else:
                time.sleep(s["s"])
        typed_end = time.monotonic() - t0  # the last keystroke: the result must stay visible after it
        time.sleep(max(0.0, tail_s))  # hold the last line on screen before we cut
        dur = time.monotonic() - t0
        _stop_ffmpeg(ff)
        ff = None
        if not mp4.exists() or mp4.stat().st_size < 1024:
            return {**BAD, "capture_id": cid, "message": "ffmpeg produced no video"}
        out = _tail(log, 1000, off=rec)  # only what the video shows (setup output is before `rec`); the cap
        # is high on purpose: how many lines scrolled off the window is what the warning below reports
        lines = out.splitlines()
        used = min(rows, len(lines)) if out.strip() else rows  # rows that carry text: the rest is blank
        cropped = _crop_empty_rows(mp4, w, h, rows, used) if crop_empty and out.strip() else None
        if cropped:  # the poster and the receipt must describe the pixels the clip now has
            w, h = cropped
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-1", "-i", str(mp4), "-frames:v", "1", str(poster)],
                       capture_output=True, timeout=30)
        sess.write_text(json.dumps({"capture_id": cid, "steps": st, "seed": seed, "cols": cols, "rows": rows,
                                    "rows_used": used, "crop_empty": crop_empty,
                                    "size": [w, h], "fps": fps, "font_size": font_size,
                                    "delay_ms": delay_ms, "jitter_ms": jitter_ms,
                                    "typing_end_s": round(typed_end, 2),
                                    "duration_s": round(dur, 2), "video": mp4.name, "poster": poster.name,
                                    "output": out}, indent=1))
        _meta(d, tool="capture_terminal_session", aspect=aspect, cols=cols, rows=rows, size=[w, h],
              font_size=font_size, typing_end_s=round(typed_end, 2))
        if not out.strip():
            status, msg = "warn", "the session captured no output"
        elif len(lines) > rows:  # the window scrolled: the first lines of the take are in no frame
            status, msg = "warn", (f"{len(lines)} lines of output in a {rows}-row window: the first "
                                   f"{len(lines) - rows} scrolled off the shot (shorten the run or raise rows)")
        else:
            status, msg = "ok", ""
        return {"status": status, "capture_id": cid, "video": str(mp4), "poster": str(poster),
                "session": str(sess), "size": [w, h], "duration_s": round(dur, 2),
                "typing_end_s": round(typed_end, 2), "font_size": font_size, "rows": rows,
                "lines": lines[-rows:], "message": msg}
    except (_StepTimeout, _XdoError) as e:
        _stop_ffmpeg(ff)
        ff = None
        for p in (mp4, poster):
            p.unlink(missing_ok=True)  # no half clip
        return {**BAD, "capture_id": cid, "message": str(e)}
    finally:
        _stop_ffmpeg(ff)
        _kill(term)
        _kill(xv)
        claim.unlink(missing_ok=True)


def capture_gui(command: str, cwd: str | None = None, seconds: float = 3.0, size: str | None = None,
                aspect: str = "16:9") -> dict:
    """Screenshot a GUI app on a throwaway X display. No GTK/Qt is installed in the image: a GTK or Qt
    app has to bring its own libraries (a custom image, or the /repo mount) to show up here."""
    _need_exec()
    wd = safe_path(cwd or config.REPO)
    size = size or S.fmt(aspect)["gui"]
    cid, d = _cap_dir()
    _meta(d, tool="capture_gui", aspect=aspect, size=size)
    try:  # '720x1280' -> the screen size _xvfb takes
        w, h = (int(v) for v in re.split(r"[xX]", size.strip()))
    except ValueError:
        return {**BAD, "message": f"size must look like WIDTHxHEIGHT, got {size!r}"}
    if not (shutil.which("Xvfb") and shutil.which("ffmpeg")):
        return {**BAD, "message": "Xvfb and ffmpeg are required"}
    disp, claim = _claim_display()  # same race as the session recorder: never share a display
    try:
        env = _clean_env(disp)
        # readiness-polled Xvfb (a fixed sleep 1.0 raced a loaded host, and a dead Xvfb surfaced as
        # "ffmpeg x11grab failed"); the same helper the session recorder uses
        xv = _xvfb(env, disp, w, h)
        app = None
        try:
            # stdout/stderr to /dev/null: nobody read the pipe, so a chatty app could block on it
            app = subprocess.Popen(["bash", "-c", command], cwd=wd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(seconds)
            alive = app.poll() is None
            path = d / "gui.png"
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", size,
                                "-i", disp, "-frames:v", "1", str(path)], capture_output=True, text=True, timeout=20)
            if r.returncode:
                return {**BAD, "message": r.stderr[-300:]}
            return {"status": "ok" if alive else "warn", "capture_id": cid, "path": str(path), "app_alive": alive,
                    "size": size,
                    "note": "" if alive else "app exited before the screenshot; screen may be empty"}
        finally:
            if app and app.poll() is None:
                os.killpg(app.pid, signal.SIGTERM)
            _kill(xv)
    finally:
        claim.unlink(missing_ok=True)
