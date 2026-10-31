from __future__ import annotations

import asyncio
import json
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP, Image

from . import capture as C, config, cutdown as CD, delivery as D, render as R, scan as SC, spec as S, tts as T, voices as V

mcp = FastMCP("storyboard-video")


async def _guard(fn, *a, **k):
    # Playwright's sync API refuses to run inside the server's event loop: use a worker thread.
    try:
        return await asyncio.to_thread(fn, *a, **k)
    except (PermissionError, FileNotFoundError, RuntimeError, KeyError, ValueError, OSError,
            subprocess.SubprocessError) as e:
        # OSError: a broken pipe/kill from Xvfb or ffmpeg is a finding like the rest, not a traceback;
        # SubprocessError: ffprobe/ffmpeg exits non-zero on a corrupt file (CalledProcessError)
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
    checks.append({"name": "chromium", "ok": ok, "fix": "set STORYBOARD_CHROMIUM or install chromium"})
    try:
        config.WORK.mkdir(parents=True, exist_ok=True)
        (config.WORK / ".w").write_text("x")
        w = True
    except OSError:
        w = False
    checks.append({"name": f"work_dir {config.WORK}", "ok": w, "fix": "mount a writable volume at STORYBOARD_WORK"})
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
    """Screenshot a running local web app (localhost/127.0.0.1/host.docker.internal only). shots=[{id, goto_path?, selector?, hide?:[css], wait_for?, settle_ms?}]. `id` (required, non-empty string) names the shot and its PNG. `goto_path` is the URL path of the page the shot navigates to (e.g. '/dashboard'), NOT a file: an output image path (.png/.jpg/.jpeg) or a container path (/work, /repo, /tmp) is rejected per shot. `path` is the old ambiguous name for `goto_path` and still works. `wait_for` is a CSS selector waited for as visible (10 s; a selector that never appears records `wait_missing` on the shot and the PNG is still taken) and `settle_ms` (integer 0..10000) is extra time to let the page paint after navigating -- pages load on 'load', never 'networkidle' (an SSE page never reaches it). Returns each shot's PNG as `shots[].path` plus a normalised `focus` box for zooming. viewport/device_scale_factor default to the aspect's capture geometry -- pass aspect='9:16' for a portrait video."""
    return await _guard(C.capture_web, url, shots, viewport, aspect, device_scale_factor)


@mcp.tool()
async def capture_terminal(command: str, cwd: str | None = None, timeout: int = 20, max_lines: int = 16,
                           cols: int | None = None, aspect: str = "16:9", crop_empty: bool = False) -> object:
    """CLI projects: run a command (clean env, empty HOME) and capture its output as terminal lines. Needs the exec plugin entry (STORYBOARD_ALLOW_EXEC=1). Use the returned capture_id or lines in a `terminal` scene. `cols` (default from the aspect: 100 for 16:9, 40 for 9:16) trims each line. `crop_empty` (default false) drops the blank lines at the end of the output so the scene does not render empty rows."""
    return await _guard(C.capture_terminal, command, cwd, timeout, max_lines, cols, aspect, crop_empty)


@mcp.tool()
async def capture_terminal_session(steps: list[dict], cols: int | None = None, rows: int | None = None,
                                  delay_ms: int = 60, jitter_ms: int = 30, seed: int = 0, fps: int = 15,
                                  cwd: str | None = None, tail_s: float = 1.2, max_s: float = 120.0,
                                  title: str = "terminal", font_size: int | None = None,
                                  aspect: str = "16:9", setup: str | None = None,
                                  crop_empty: bool = False) -> object:
    """CLI projects: record a REAL terminal session (xterm in Xvfb, typed with xdotool, grabbed with x11grab) into an MP4. steps=[{type:'type',text}|{type:'key',key}|{type:'wait_for',text,timeout_s}|{type:'hold_s',s}]. Only the typing speed is staged; the shell and its output are real. cols/rows/font_size default to the aspect's geometry: 80x16 at font 22 for 16:9, 44x28 at 15 for 9:16 (a window that fills the frame); pass rows = printed lines + 1 to size the window to the run. `crop_empty` (default false) trims the recorded frames down to the rows that carry text, so a short run is not half a screen of empty rows. Needs STORYBOARD_ALLOW_EXEC=1. Use video+poster in a `terminal` scene."""
    return await _guard(C.capture_terminal_session, steps, cols, rows, delay_ms, jitter_ms, seed, fps, cwd, tail_s,
                        max_s, title, font_size, aspect, setup, crop_empty)


@mcp.tool()
async def capture_gui(command: str, cwd: str | None = None, seconds: float = 3.0, size: str | None = None,
                     aspect: str = "16:9") -> object:
    """GUI projects: launch the app on a virtual X display (Xvfb), wait, screenshot it. Needs STORYBOARD_ALLOW_EXEC=1. Use the PNG in an `image` scene. size defaults to the aspect's screen (1280x720 / 720x1280)."""
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
async def suggest_voices(lang: str, pitch: str = "any", pace: str = "any", flow: str = "any",
                         emotion: str = "any", n: int = 3) -> object:
    """Rank the Pocket TTS voices for a user's answers (ask them first, then set spec.voice to a pick). pitch=low|high, pace=slow|normal|fast, flow=smooth|breathy (breathy = more pauses), emotion=calm|neutral|expressive; 'any' = no opinion. lang=pt-BR|en. Returns the top n with measured pace/pause/intonation, license (CC-BY-4.0 needs attribution) and a caveat: naturalness is NOT measured, so audition with narrate(scratch=true)."""
    return await _guard(lambda: V.suggest(lang, n, pitch=pitch, pace=pace, flow=flow, emotion=emotion))


@mcp.tool()
async def narrate(spec_hash: str, scratch: bool = False) -> object:
    """Offline voice-over (Pocket TTS): synthesize each scene.narration into one WAV under /work/audio/<spec_hash>/ and write manifest.json with the measured durations. Cached on text+voice+lang, so re-running only synthesizes changed lines. A scene then lasts max(duration_s, audio+0.4s) and the resolved spec_hash changes, so re-run stills before a delivery render. Needs spec.lang (pt-BR|en); spell identifiers with spec.say. `scratch=true` is the animatic pass: same engine, same cache, same WAVs, the manifest is only labelled (`"scratch": true`) and the final resolved_hash does not change."""
    return await _guard(T.narrate, spec_hash, scratch)


@mcp.tool()
async def animatic(spec_hash: str) -> object:
    """Rough cut for judging rhythm before any capture: every scene becomes a card with its visual placeholder ("[captura: sessao de terminal: X — 6.0s]") and its own line's audio, 360p, 15 fps, an ANIMATIC watermark and no music. Same render path as the delivery, no capture needed. Runs in the background like `render`: returns job_id, poll render_status (a 3-minute script takes over a minute). The receipt writes /work/animatic/<id>_ANIMATIC.mp4 (outside out/<resolved_hash>/, so it is never mistaken for the final video) and carries the path plus `pace_map` per scene {id, dur_s, words, wps, lead_s, tail_s, type} -- read its `caveat`: a synth is more regular than a human, so judge structure here and recompute with the final voice."""
    return await _guard(lambda: {"status": "ok", "job_id": R.start(spec_hash, "animatic")})


@mcp.tool()
async def shot_list(spec_hash: str) -> object:
    """The captures this AV script still needs, scene by scene and in playback order, each with the time the voice left for it (`hold_s` after the line ends, `silent_s` = lead+tail of the whole scene) and the `file:line` evidence the shot has to prove. Feed each row to capture_web / capture_terminal_session / capture_gui / extract_code so a capture records what the script needs, not what fits."""
    return await _guard(R.shot_list, spec_hash)


@mcp.tool()
async def stills(spec_hash: str, at_s: float | None = None) -> list:
    """Render one small JPEG per scene (the review step), each with its layout audit and a `digest` of the frame. `at_s` shoots that second inside every scene instead (the review frame is 75% in), so two calls with different `at_s` and the same `digest` prove the card stopped moving. Look at every image before approving; required before a delivery render."""
    try:
        res = await asyncio.to_thread(R.stills, spec_hash, at_s)
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
    """Progress (0..1), status running|done|error, elapsed_s since the job started, and the result receipt when done."""
    return R.status(job_id)


@mcp.tool()
async def verify(video: str, spec_hash: str) -> object:
    """Check the rendered MP4 against the spec: size (1080x1920 for a 9:16 delivery), fps, duration (+-1 frame), non-blank frames at 5/50/95%, the credit block (`credits_missing` when a track needs a credit and neither /work/CREDITS.txt nor out/<resolved_hash>/CREDITS.txt carries it), and the audio: the stream must be as long as the picture (+-0.1 s), EBU R128 integrated within 1.5 LU of the target (-14 LUFS default), true peak <= -1.0 dBTP, and no silence longer than 3 s in a narrated video. Returns the measured numbers as `loudness` {integrated_lufs, lra_lu, true_peak_db}, `silences` and the track's `music_license`; `audio` is null when silent, `narrated` tells which bar applied. Errors when the file is missing."""
    return await _guard(R.verify, video, spec_hash)


@mcp.tool()
def cutdown(spec_hash: str, target_s: float) -> object:
    """Cut the spec down to target_s (e.g. 30 or 15 for an ad) by removing whole scenes by arc role (implication, extra value, problem, tail); hook, proof, result and cta are never removed and the voice is never sped up. Needs direction.scenes roles. Returns the new spec_hash, `removed` [{scene, reason}] and its lint, or an error with code and min_s (cutdown_infeasible, hook_promise_unkept, cutdown_needs_roles)."""
    try:
        res = CD.cutdown(S.load(spec_hash), float(target_s))
        h = S.persist(res["spec"])  # inside the guard: an unwritable /work is an error dict, not a traceback
    except CD.CutdownError as e:
        return {"status": "error", "code": e.code, "min_s": e.min_s, "message": str(e)}
    except (FileNotFoundError, ValueError, OSError) as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}
    return {"status": "ok", "spec_hash": h, "from": spec_hash, "removed": res["removed"],
            "duration_s": res["duration_s"], "duration_basis": res.get("duration_basis"), "findings": res["lint"]}


@mcp.tool()
async def deliver(spec_hash: str, project: str, aspect: str, version: int, date: str, quality: str = "delivery") -> object:
    """Ship a finished render as deliveries/<project>_vNN_<16x9|9x16>_<date>.mp4 in the work dir, with its .srt and CREDITS.txt beside it: older deliveries of the same project and aspect move to deliveries/archive/, deliveries/CURRENT points at the new one. Only the quality='delivery' render is publishable, and the delivery check (SRT, CREDITS.txt, licences) runs first; errors block it."""
    def go():
        if quality != "delivery":
            return {"status": "error", "findings": [{
                "severity": "error", "code": "quality_not_delivery",
                "message": f"deliver publishes out/<hash>/delivery.mp4, not the {quality!r} render",
                "fix": "render with quality='delivery' (and verify it), then deliver again"}]}
        spec = S.load(spec_hash)
        out = config.WORK / "out" / S.resolved_hash(spec)
        found = D.delivery_check(spec, out)
        missing = [p.name for p in (out / "delivery.mp4", out / "delivery.srt") if not p.is_file()]
        if missing:  # a draft-only dir has a draft.srt: the check alone would pass and ship a preview
            found.insert(0, {"severity": "error", "code": "render_missing",
                             "message": f"no {', '.join(missing)} in {out}",
                             "fix": "render with quality='delivery' for this spec_hash, then deliver again"})
        if any(f["severity"] == "error" for f in found):
            return {"status": "error", "findings": found}
        try:
            return {"status": "ok", "findings": found,
                    **D.deliver(project, aspect, version, date, out / f"{quality}.mp4")}
        except D.DeliveryError as e:
            return {"status": "error", "findings": [{"severity": "error", "code": e.code,
                                                      "message": str(e), "fix": e.fix}]}
    return await _guard(go)


@mcp.tool()
def round_log(n: int, question: str, notes: list[dict] | None = None, decision: str = "", hash_before: str = "", hash_after: str = "") -> object:
    """Record one review round as /work/rounds/<n>.md: the question, notes [{timecode, severity must|pref, text}], the decision and the spec_hash before/after."""
    try:
        return {"status": "ok", "path": D.round_log(config.WORK, n, question, notes, decision, hash_before, hash_after)}
    except (ValueError, OSError, PermissionError) as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
