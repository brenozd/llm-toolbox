from __future__ import annotations

import asyncio
import json
import shutil

from mcp.server.fastmcp import FastMCP, Image

from . import capture as C, config, render as R, scan as SC, spec as S, tts as T

mcp = FastMCP("promo-video")


async def _guard(fn, *a, **k):
    # Playwright's sync API refuses to run inside the server's event loop: use a worker thread.
    try:
        return await asyncio.to_thread(fn, *a, **k)
    except (PermissionError, FileNotFoundError, RuntimeError, KeyError, ValueError) as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


@mcp.tool()
async def preflight() -> object:
    """Check ffmpeg, ffprobe, chromium, Xvfb, writable work dir and exec mode. Run first."""
    return await asyncio.to_thread(_preflight)


def _preflight() -> dict:
    checks = []
    for name, fix in [("ffmpeg", "install ffmpeg"), ("ffprobe", "install ffmpeg"),
                      ("Xvfb", "install xvfb (only needed for capture_gui and capture_terminal_session)"),
                      ("xdotool", "install xdotool (only needed for capture_terminal_session)"),
                      ("xterm", "install xterm (only needed for capture_terminal_session)")]:
        checks.append({"name": name, "ok": bool(shutil.which(name)), "fix": fix})
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(args=R.ARGS, executable_path=config.chromium()).close()
        ok = True
    except Exception as e:
        ok = False
        checks.append({"name": "chromium_error", "ok": False, "fix": str(e)[:200]})
    checks.append({"name": "chromium", "ok": ok, "fix": "set PROMO_CHROMIUM or install chromium"})
    try:
        config.WORK.mkdir(parents=True, exist_ok=True)
        (config.WORK / ".w").write_text("x")
        w = True
    except OSError:
        w = False
    checks.append({"name": f"work_dir {config.WORK}", "ok": w, "fix": "mount a writable volume at PROMO_WORK"})
    checks.append({"name": f"repo {config.REPO}", "ok": config.REPO.exists(), "fix": "mount the target repo read-only at /repo"})
    return {"status": "ok" if all(c["ok"] for c in checks if c["name"] not in ("Xvfb", "xdotool", "xterm")) else "error",
            "exec_enabled": config.ALLOW_EXEC, "checks": checks}


@mcp.tool()
async def scan_repo(repo: str | None = None, max_files: int = 6000) -> object:
    """Read-only recon of the repo: stack, kind guess (web|cli|gui|mcp|lib), README facts with file:line evidence, commands, logos. Never opens secret files."""
    return await _guard(SC.scan_repo, repo, max_files)


@mcp.tool()
async def brand_tokens(repo: str | None = None) -> object:
    """Colors/fonts from CSS/QSS/Tailwind with found|guess provenance and an auto contrast fix. Feed `theme` into the spec."""
    return await _guard(SC.brand_tokens, repo)


@mcp.tool()
async def extract_code(path: str, lines: str, repo: str | None = None) -> object:
    """Return up to 18 lines of a repo file as a code snippet plus its file:line evidence. lines like '10-24'."""
    return await _guard(SC.extract_code, repo, path, lines)


@mcp.tool()
async def capture_web(url: str, shots: list[dict], viewport: dict | None = None, aspect: str = "16:9",
                      device_scale_factor: float | None = None) -> object:
    """Screenshot a running local web app (localhost/127.0.0.1/host.docker.internal only). shots=[{id, selector?, hide?:[css], path?}]. Returns PNG paths and a normalised `focus` box for zooming. viewport/device_scale_factor default to the aspect's capture geometry -- pass aspect='9:16' for a portrait video."""
    return await _guard(C.capture_web, url, shots, viewport, aspect, device_scale_factor)


@mcp.tool()
async def capture_terminal(command: str, cwd: str | None = None, timeout: int = 20, max_lines: int = 16,
                           cols: int | None = None, aspect: str = "16:9") -> object:
    """CLI projects: run a command (clean env, empty HOME) and capture its output as terminal lines. Needs the exec plugin entry (PROMO_ALLOW_EXEC=1). Use the returned capture_id or lines in a `terminal` scene. `cols` (default from the aspect: 100 for 16:9, 40 for 9:16) trims each line."""
    return await _guard(C.capture_terminal, command, cwd, timeout, max_lines, cols, aspect)


@mcp.tool()
async def capture_terminal_session(steps: list[dict], cols: int | None = None, rows: int | None = None,
                                  delay_ms: int = 60, jitter_ms: int = 30, seed: int = 0, fps: int = 15,
                                  cwd: str | None = None, tail_s: float = 1.2, max_s: float = 120.0,
                                  title: str = "terminal", font_size: int | None = None,
                                  aspect: str = "16:9", setup: str | None = None) -> object:
    """CLI projects: record a REAL terminal session (xterm in Xvfb, typed with xdotool, grabbed with x11grab) into an MP4. steps=[{type:'type',text}|{type:'key',key}|{type:'wait_for',text,timeout_s}|{type:'hold_s',s}]. Only the typing speed is staged; the shell and its output are real. cols/rows/font_size default to the aspect's geometry: 80x16 at font 22 for 16:9, 44x28 at 15 for 9:16 (a window that fills the frame). Needs PROMO_ALLOW_EXEC=1. Use video+poster in a `terminal` scene."""
    return await _guard(C.capture_terminal_session, steps, cols, rows, delay_ms, jitter_ms, seed, fps, cwd, tail_s,
                        max_s, title, font_size, aspect, setup)


@mcp.tool()
async def capture_gui(command: str, cwd: str | None = None, seconds: float = 3.0, size: str | None = None,
                     aspect: str = "16:9") -> object:
    """GUI projects: launch the app on a virtual X display (Xvfb), wait, screenshot it. Needs PROMO_ALLOW_EXEC=1. Use the PNG in an `image` scene. size defaults to the aspect's screen (1280x720 / 720x1280)."""
    return await _guard(C.capture_gui, command, cwd, seconds, size, aspect)


@mcp.tool()
def validate_spec(spec: dict) -> object:
    """Lint a video spec and persist it. Returns findings[{severity,code,scene,fix}], spec_hash and duration. Every later tool needs spec_hash. Errors block rendering."""
    s = S.normalize(spec)
    f = S.lint(s)
    ok = not any(x["severity"] == "error" for x in f)
    out = {"status": "ok" if ok else "error", "findings": f}
    if ok:
        out["spec_hash"] = S.persist(s)
        tl = S.timeline(s)
        out.update(duration_s=round(tl["frames"] / tl["fps"], 2), frames=tl["frames"])
    return out


@mcp.tool()
def reframe(spec_hash: str, aspect: str = "9:16") -> object:
    """Clone a spec into the other aspect (9:16 or 16:9) and apply that format's rules: portrait keeps max 4 bullets per scene and trims terminal lines to ~40 cols. Returns the new spec_hash, every edit it made, and the captures that must be redone for the new format (geometry is baked into the pixels)."""
    try:
        base = S.load(spec_hash)
        res = S.reformat(base, aspect)
    except (FileNotFoundError, ValueError) as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}
    h = S.persist(res["spec"])
    return {"status": "ok", "spec_hash": h, "from": spec_hash, "aspect": aspect,
            "changes": res["changes"], "recaptures": res["recaptures"],
            "findings": S.lint(res["spec"])}


@mcp.tool()
async def narrate(spec_hash: str) -> object:
    """Offline voice-over (Kokoro-82M): synthesize each scene.narration into one WAV under /work/audio/<spec_hash>/ and write manifest.json with the measured durations. Cached on text+voice+speed+lang, so re-running only synthesizes changed lines. A scene then lasts max(duration_s, audio+0.4s) and the resolved spec_hash changes, so re-run stills before a delivery render. Needs spec.lang (pt-BR|en); spell identifiers with spec.say."""
    return await _guard(T.narrate, spec_hash)


@mcp.tool()
async def stills(spec_hash: str) -> list:
    """Render one small JPEG per scene (the review step), each with the layout audit for that frame (text outside the frame, inside the 9:16 safe zones, or cut off inside its box). Look at every image before approving; required before a delivery render."""
    try:
        res = await asyncio.to_thread(R.stills, spec_hash)
    except Exception as e:
        return [json.dumps({"status": "error", "message": f"{type(e).__name__}: {e}"})]
    warn = [f for r in res for f in r["findings"]]
    return [json.dumps({"status": "ok", "stills": res, "audit_warnings": len(warn)})] + [Image(path=r["path"]) for r in res]


@mcp.tool()
async def audit_layout(spec_hash: str) -> object:
    """Layout audit without screenshots: measures every text box of every scene and warns when it leaves the frame, sits in the 9:16 safe zone (top 10% / bottom 20% / sides 5%), or has content cut off inside its box. Also reports where an image scene's zoom puts its focus box."""
    return await _guard(R.audit, spec_hash)


@mcp.tool()
async def render(spec_hash: str, quality: str = "draft") -> object:
    """Start a background render (quality draft|delivery). Returns job_id; poll render_status. Output is MP4 + SRT + poster in the work dir, plus /work/CREDITS.txt and out/<resolved_hash>/CREDITS.txt when the spec has music."""
    if quality not in ("draft", "delivery"):
        return {"status": "error", "message": "quality must be draft or delivery"}
    if quality == "delivery" and not R.stills_done(spec_hash):
        return {"status": "error", "message": "run stills for this spec_hash first"}
    return await _guard(lambda: {"status": "ok", "job_id": R.start(spec_hash, quality)})


@mcp.tool()
def render_status(job_id: str) -> object:
    """Progress (0..1), status running|done|error, and the result receipt when done."""
    return R.JOBS.get(job_id) or {"status": "error", "message": "unknown job_id"}


@mcp.tool()
async def verify(video: str, spec_hash: str) -> object:
    """Check the rendered MP4 against the spec: size (1080x1920 for a 9:16 delivery), fps, duration (+-1 frame), non-blank frames at 5/50/95%, the credit block (`credits_missing` when a track needs a credit and neither /work/CREDITS.txt nor out/<resolved_hash>/CREDITS.txt carries it), and the audio: the stream must be as long as the picture (+-0.1 s), EBU R128 integrated within 1.5 LU of -16 LUFS, true peak <= -1.5 dBTP, and no silence longer than 3 s in a narrated video. Returns the measured numbers as `loudness` {integrated_lufs, lra_lu, true_peak_db}, `silences` and the track's `music_license`; `audio` is null when silent, `narrated` tells which bar applied. Errors when the file is missing."""
    return await _guard(R.verify, video, spec_hash)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
