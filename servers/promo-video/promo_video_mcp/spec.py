from __future__ import annotations

import collections
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from . import config
from .safety import safe_path

TYPES = {"title", "bullets", "terminal", "image", "code"}
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
STAT = re.compile(r"\b\d[\d.,]*\s*(%|x|×|ms|k|M|\+)", re.I)
LANGS = {"pt-BR", "en"}
AUDIO_TAIL = 0.4  # silence after the spoken line: the scene never cuts on the last syllable
MAX_WPS = 3.2  # words per second a TTS voice comfortably fits in a scene
MIN_HOLD_S = 4.0  # the last line of a recorded terminal must stay on screen this long
TTS_TOKEN = re.compile(r"\b(?:[A-Z]{2,}[A-Z0-9]*|[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]*|[A-Za-z]+\d[A-Za-z0-9]*)\b")
# Symbols a voice cannot read back plainly: --flags, file:line, a/b, KEY=1 (never plain words).
TTS_SYMBOL = re.compile(r"(?<!\w)(?:--[A-Za-z][\w-]*|[A-Za-z0-9_]+[/:=][A-Za-z0-9_]+)(?!\w)")
ZOOM_RANGE = (1.0, 4.0)  # scene.zoom: 1 = the whole capture, more = crop in
THEME = {"bg": "#0f1115", "fg": "#f2f4f8", "accent": "#4cc2ff", "muted": "#8b93a1"}
# spec.music levels: a bed sits well under the voice and drops further while someone speaks.
MUSIC_DEFAULTS = {"volume_db": -18.0, "duck": 12.0}

# Capture geometry per delivery format. The format is baked into the pixels, so a 16:9 video is
# assembled from 16:9 captures and a 9:16 video from portrait ones -- never from rescaled landscape.
# cols/rows/font are the *terminal* geometry: the grid aspect has to match the content box, or
# whatever the window is short of leaves black frame around a stamp of small text. Measured with
# xdotool in the image (font 22 = ~18x37 px cell, font 15 = ~13x25): 80x16 is 2.4:1 (content box
# 2.1:1 without a heading, 2.5:1 with one) and 44x28 is 0.83:1 (portrait content box 0.81:1), so
# _box_scale fills the width instead of being capped by the height.
FORMATS = {
    "16:9": {"viewport": {"width": 1440, "height": 810}, "device_scale_factor": 1,
             "cols": 80, "rows": 16, "font": 22, "gui": "1280x720", "max_cols": 100},
    "9:16": {"viewport": {"width": 540, "height": 960}, "device_scale_factor": 2,
             "cols": 44, "rows": 28, "font": 15, "gui": "720x1280", "max_cols": 40},
}
# What a portrait frame has no room for. Lossy, so reformat() reports every dropped line.
PORTRAIT = {"max_bullets": 4}


def normalize(spec: dict) -> dict:
    s = json.loads(json.dumps(spec))
    s.setdefault("fps", 30)
    s.setdefault("aspect", "16:9")
    s.setdefault("transition_s", 0.5)
    s["theme"] = {**THEME, **(s.get("theme") or {})}
    if isinstance(s.get("music"), dict):  # a track the music-search skill staged, plus the mix levels
        s["music"] = {"volume_db": MUSIC_DEFAULTS["volume_db"], "duck": MUSIC_DEFAULTS["duck"], **s["music"]}
    for sc in s.get("scenes", []):
        sc.setdefault("duration_s", 3.0)
    return s


def spec_hash(spec: dict) -> str:
    return hashlib.sha256(json.dumps(normalize(spec), sort_keys=True).encode()).hexdigest()[:12]


def size(spec: dict) -> tuple[int, int]:
    return ASPECTS[spec["aspect"]]


def fmt(aspect: str) -> dict:
    if aspect not in FORMATS:
        raise ValueError(f"aspect must be one of {sorted(FORMATS)}")
    return FORMATS[aspect]


def audio_manifest(spec: dict) -> dict:
    """The narration manifest narrate() wrote for this spec, or {} when there is none."""
    p = config.WORK / "audio" / spec_hash(spec) / "manifest.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def audio_digest(spec: dict) -> str:
    """Digest of the WAVs the spec currently resolves against (the cache keys are text+voice+speed+lang)."""
    keys = {sid: v.get("key") for sid, v in (audio_manifest(spec).get("scenes") or {}).items()}
    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()[:12] if keys else ""


def resolved_hash(spec: dict) -> str:
    """spec_hash *plus* its narration *plus* the engine identity: new speech, a new TTS model or a
    template change (RENDER_VERSION) gives a new id, so stills and renders made for the old
    voice-over/template are never reused (either one changes the picture)."""
    return hashlib.sha256(f"{spec_hash(spec)}:{audio_digest(spec)}:{config.RENDER_VERSION}:"
                          f"{config.model_id()}".encode()).hexdigest()[:12]


def timeline(spec: dict) -> dict:
    """Single source of truth for scene frames; stills, render and verify all use it.

    A scene lasts at least as long as its narration plus AUDIO_TAIL, so speech is never cut off. It also
    pays for the transition it is overlapped by, so the *next* scene never starts before the line ends."""
    fps = spec["fps"]
    audio = {sid: float(v.get("duration_s") or 0) for sid, v in (audio_manifest(spec).get("scenes") or {}).items()}
    t = round(spec["transition_s"] * fps)
    durs = [round(max(sc["duration_s"], audio.get(sc["id"], 0) + AUDIO_TAIL + t / fps if audio.get(sc["id"]) else 0)
                  * fps) for sc in spec["scenes"]]
    t = max(0, min(t, min(durs) // 2 - 1)) if durs else 0
    out, start = [], 0
    for i, d in enumerate(durs):
        out.append({"id": spec["scenes"][i]["id"], "start": start, "dur": d})
        start += d - t
    total = out[-1]["start"] + out[-1]["dur"] if out else 0
    return {"fps": fps, "trans": t, "scenes": out, "frames": total}


def _texts(sc: dict) -> list[str]:
    parts = [sc.get("title"), sc.get("subtitle"), sc.get("heading"), sc.get("caption")] + list(sc.get("items") or [])
    return [p for p in parts if isinstance(p, str)]


def _narration(sc: dict) -> str:
    return sc["narration"] if isinstance(sc.get("narration"), str) else ""


def _spoken_tokens(text: str, sc: dict) -> list[str]:
    """Tokens a TTS voice will mangle: acronyms, snake/camelCase and symbols (LD_PRELOAD, snake_case,
    camelCase, --flag, file:line) plus any identifier from the *code/terminal* the scene shows.

    Bullets are prose, not code: treating them as identifiers made `say_missing` warn about "the",
    "and" or "repo" in an ordinary sentence, so only the code and the captured lines are sources."""
    code = " ".join([str(sc.get("code") or ""), *(str(x) for x in (sc.get("lines") or []))])
    shown = {t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", code) if len(t) > 2}
    out = TTS_TOKEN.findall(text) + TTS_SYMBOL.findall(text)
    out += [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text) if t in shown and t not in out]
    return out


def _exists(path: str) -> bool:
    """A spec path is either absolute (a capture under /work) or repo-relative."""
    p = Path(path).expanduser()
    return (p if p.is_absolute() else config.REPO / p).is_file()


def _mid_frame(path: str, w: int = 96, h: int = 60) -> bytes | None:
    """One small gray frame from the middle of the clip: frame 0 of a recording is the blank
    pre-roll, so the first frame proves nothing about what the take ended up showing."""
    if not shutil.which("ffmpeg"):
        return None
    seek: list[str] = []
    if shutil.which("ffprobe"):
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                               capture_output=True, text=True, timeout=20)
            dur = float(r.stdout.strip() or 0)
            seek = ["-ss", f"{dur / 2:.3f}"] if dur > 0.2 else []
        except (OSError, subprocess.SubprocessError, ValueError):
            seek = []
    try:
        r = subprocess.run(["ffmpeg", "-loglevel", "error", *seek, "-i", path, "-frames:v", "1",
                            "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if len(r.stdout) >= w * h else None


def _ink_ratio(px: bytes) -> float:
    """Share of pixels that are not the dominant (background) colour: a '$ ' prompt on a black
    screen is a few pixels, so raw variance hides it while this does not."""
    if not px:
        return 0.0
    counts = collections.Counter(px)
    bg = counts.most_common(1)[0][0]
    return sum(n for v, n in counts.items() if abs(v - bg) > 8) / len(px)


def _sparse(path: str) -> bool:
    """True for a near-empty capture: a screen with nothing but a background and a prompt proves
    nothing, whether it is black (nothing rendered) or white (blank page). Never raises, so lint
    stays cheap."""
    if not shutil.which("ffmpeg") or not _exists(path):
        return False
    px = _mid_frame(path)
    return px is not None and _ink_ratio(px) < 0.005  # a bare '$ ' measures ~0.1%, two real lines 5%


def music_verdict(license: str) -> str:
    """allow | attribution | deny, derived from the licence string alone (never from a passed-in field).

    A promo is published and commercial, and syncing is an adaptation: NC, ND and SA are always out.
    Everything that is not a known CC0 / public-domain / CC BY string is out too: an allow-list fails
    closed, a deny-list lets "All rights reserved" (or a bespoke EULA) through uncredited."""
    toks = set(re.split(r"[^a-z0-9]+", str(license or "").lower()))
    if toks & {"nc", "nd", "sa"}:  # CC BY-NC / -ND / -SA, however it is written
        return "deny"
    if "by" in toks:  # CC BY 4.0, or a licence URL carrying /by/
        return "attribution"
    if toks & {"cc0", "pdm", "pd", "publicdomain"} or {"public", "domain"} <= toks:
        return "allow"
    return "deny"  # unknown: never assume a licence the skill did not report


def has_license_url(music: dict) -> bool:
    """A CC BY credit has to link the licence it grants: a bare "CC BY 4.0" is not an attribution."""
    if str(music.get("license_url") or "").strip().lower().startswith(("http://", "https://")):
        return True
    return bool(re.search(r"https?://", str(music.get("attribution") or "")))


def _lint_music(music, add) -> list[dict]:
    """spec.music points at a track the music-search skill staged under /music (/work or /repo also
    resolve): a path that is not there would silently render a silent video, and a licence the promo
    cannot use (or a BY track with no credit) must never reach a published video."""
    if not isinstance(music, dict):
        add("error", "bad_music", None, "music must be an object",
            'spec.music = {"path": "/music/<id>.mp3", "license": "CC0 1.0", "volume_db": -18, "duck": 12}')
        return []
    p = music.get("path")
    roots = [config.MUSIC_DIR, config.WORK, config.REPO]
    try:
        ok = isinstance(p, str) and bool(p) and safe_path(p, roots).is_file()
    except PermissionError:
        ok = False
    if not ok:  # a typo, an unmounted /music, or a path outside the roots
        add("error", "music_path_missing", None, f"music.path {p!r} is not a file under /music, /work or /repo",
            "stage the track with the music-search skill and use its /music/<id> path")
    lic = music.get("license")
    if not isinstance(lic, str) or not lic.strip():
        add("error", "music_license_missing", None, "music.license missing",
            'set the licence the music-search skill reported, e.g. "CC0 1.0" or "CC BY 4.0"')
    elif music_verdict(lic) == "deny":
        add("error", "music_license_incompatible", None, f"licence {lic!r} cannot be used in a promo",
            "use CC0 1.0, public domain or CC BY 4.0: NC/ND/SA are out (commercial, and syncing is an "
            "adaptation) and so is any string the skill did not report as one of those")
    elif music_verdict(lic) == "attribution" and not str(music.get("attribution") or "").strip():
        add("error", "music_license_missing", None, f"{lic} needs an attribution and music.attribution is empty",
            "paste the credit string the music-search skill returned (creator, licence link, changes line)")
    elif music_verdict(lic) == "attribution" and not has_license_url(music):
        add("error", "music_license_missing", None, f"{lic} needs a licence link and music.license_url is empty",
            "paste the licence URL the music-search skill returned (or put it inside the attribution)")
    st = music.get("start_s")
    if st is not None and (isinstance(st, bool) or not isinstance(st, (int, float))
                           or not 0 <= st < 1e6):  # "abc" kills render, -5 empties the trim, nan poisons ffmpeg
        add("error", "bad_music_start", None, f"start_s {st!r}",
            "use a number of seconds >= 0, as the music-search skill reported it")
    vol = music.get("volume_db")
    lo, hi = config.MUSIC_VOLUME_DB
    if isinstance(vol, bool) or not isinstance(vol, (int, float)) or not (lo <= vol <= hi):
        add("error", "bad_music_volume", None, f"volume_db {vol!r}", f"use a number in {lo}..{hi}")
    duck = music.get("duck")
    lo, hi = config.MUSIC_DUCK_DB
    if isinstance(duck, bool) or not isinstance(duck, (int, float)) or not (lo <= duck <= hi):
        add("error", "bad_music_duck", None, f"duck {duck!r}", f"use a number of dB in {lo}..{hi}")
    return []


def _lint_focus_zoom(sc: dict, sid, add) -> None:
    """scene.focus/zoom are fractions of the capture: out-of-range numbers silently crop the wrong
    part of the picture (or nothing at all), so they are rejected here instead of at render time."""
    fo = sc.get("focus")
    if fo is not None:
        ok = (isinstance(fo, dict)
              and all(isinstance(fo.get(k), (int, float)) and not isinstance(fo.get(k), bool)
                      for k in ("x", "y", "w", "h")))
        if not ok:
            add("error", "bad_focus", sid, f"focus {fo!r}", 'focus is {x,y,w,h} fractions of the capture (0..1)')
        elif not all(0.0 <= fo[k] <= 1.0 for k in ("x", "y", "w", "h")) \
                or fo["w"] <= 0 or fo["h"] <= 0 \
                or fo["x"] + fo["w"] > 1.0 + 1e-6 or fo["y"] + fo["h"] > 1.0 + 1e-6:
            add("error", "bad_focus", sid, f"focus {fo!r} is not inside the capture",
                "use 0 <= x,y and w,h > 0 with x+w <= 1 and y+h <= 1 (the focus capture_web returns)")
    z = sc.get("zoom", 1.6)
    lo, hi = ZOOM_RANGE
    if isinstance(z, bool) or not isinstance(z, (int, float)) or not (lo <= z <= hi):
        add("error", "bad_zoom", sid, f"zoom {z!r}", f"use a number in {lo}..{hi} (1 = the whole capture)")


def _hold_gap(sc: dict) -> float | None:
    """Seconds between the end of typing in the recorded take and the end of the scene, or None when
    the capture did not record when typing stopped (an older take)."""
    cid, _ = _capture_of(sc)
    if not cid:
        return None
    m = capture_meta(cid)
    end = m.get("typing_end_s")
    return float(end) if isinstance(end, (int, float)) and not isinstance(end, bool) else None


def lint(spec: dict) -> list[dict]:
    f: list[dict] = []

    def add(sev, code, scene, msg, fix):
        f.append({"severity": sev, "code": code, "scene": scene, "message": msg, "fix": fix})

    if not isinstance(spec.get("scenes"), list) or not spec["scenes"]:
        add("error", "no_scenes", None, "spec has no scenes", "add at least one scene")
        return f
    if spec["aspect"] not in ASPECTS:
        add("error", "bad_aspect", None, f"aspect {spec['aspect']}", "use 16:9 or 9:16")
    if not (10 <= spec["fps"] <= 60):
        add("error", "bad_fps", None, f"fps {spec['fps']}", "use 10..60")
    lang = spec.get("lang")
    if lang is not None and lang not in LANGS:
        add("error", "bad_lang", None, f"lang {lang!r}", f"use one of {sorted(LANGS)}")
    if "say" in spec and not isinstance(spec["say"], dict):
        add("error", "bad_say", None, "say must be a {written: spoken} object",
            'spec.say = {"LD_PRELOAD": "el di preload"}')
    if not lang and any(_narration(sc) for sc in spec["scenes"] if isinstance(sc, dict)):
        add("error", "missing_lang", None, "narration without spec.lang", "set lang to pt-BR or en")
    say = spec.get("say") if isinstance(spec.get("say"), dict) else {}
    if spec.get("music") is not None:
        f += _lint_music(spec.get("music"), add)
    seen = set()
    for sc in spec["scenes"]:
        sid = sc.get("id")
        if not sid or sid in seen:
            add("error", "bad_id", sid, "missing or duplicate scene id", "give each scene a unique id")
        seen.add(sid)
        ty = sc.get("type")
        if ty not in TYPES:
            add("error", "bad_type", sid, f"type {ty}", f"use one of {sorted(TYPES)}")
            continue
        if not (1.5 <= sc["duration_s"] <= 12):
            add("error", "duration", sid, f"{sc['duration_s']}s", "use 1.5..12 s")
        need = {"title": ["title"], "bullets": ["heading", "items"], "terminal": [], "image": ["image"], "code": ["code", "source"]}[ty]
        for k in need:
            if not sc.get(k):
                add("error", "missing_field", sid, f"{ty} needs '{k}'", f"set {k}")
        if ty == "bullets" and len(sc.get("items") or []) > 5:
            add("error", "too_many_items", sid, "more than 5 bullets", "split the scene")
        if ty == "terminal":
            n = len(sc.get("lines") or [])
            if not n and not sc.get("capture_id") and not sc.get("video"):
                add("error", "missing_field", sid, "terminal needs 'lines', 'capture_id' or 'video'",
                    "run capture_terminal or capture_terminal_session")
            if n > 18:
                add("error", "too_many_lines", sid, f"{n} lines", "max 18; trim the capture")
        for key in ("image", "video", "poster"):
            p = sc.get(key)
            if not isinstance(p, str):
                continue
            if not _exists(p):  # without this a typo only explodes later, inside stills/render
                add("error", "missing_file", sid, f"{key} path does not exist: {p}",
                    "re-run the capture (or fix the path); relative paths are resolved against the repo")
            elif _sparse(p):
                add("warn", "sparse_capture", sid, f"{key} looks near-empty (a blank, single-colour screen)",
                    "re-run the capture; check the command really printed something")
        if ty == "image":
            _lint_focus_zoom(sc, sid, add)
        if ty == "code" and len((sc.get("code") or "").splitlines()) > 18:
            add("error", "too_many_lines", sid, "code longer than 18 lines", "extract fewer lines")
        for t in _texts(sc):
            if len(t.split()) > 18:
                add("warn", "wordy", sid, f"{len(t.split())} words", "keep on-screen text under 18 words")
        if ty == "terminal" and (sc.get("video") or sc.get("capture_id")):
            end = _hold_gap(sc)
            if end is not None:
                durs = {x["id"]: x["dur"] / spec["fps"] for x in timeline(spec)["scenes"]}
                dur = durs.get(sid, float(sc["duration_s"]))
                if dur < end + MIN_HOLD_S - 1e-6:
                    add("warn", "short_hold", sid,
                        f"the scene is {dur:g}s but the take stops typing at {end:g}s: the final output stays "
                        f"visible only {dur - end:g}s",
                        f"set duration_s >= {end + MIN_HOLD_S:.1f} so the result is on screen for >= {MIN_HOLD_S:g}s")
        narr = _narration(sc)
        for t in [*_texts(sc), sc.get("evidence_caption")]:
            if isinstance(t, str) and re.search(r"(?<![\w.])/(work|repo|tmp)/", t):
                add("warn", "container_path", sid, f"on-screen text shows a container path: '{t[:40]}'",
                    "show a repo-relative path or drop it: viewers cannot use /work or /repo")
        for t in [*_texts(sc), narr]:  # a spoken number is a claim too: it needs the same evidence
            if t and STAT.search(t) and not sc.get("evidence"):
                add("error", "uncited_stat", sid, f"number claim in '{t[:40]}'", "add scene.evidence = 'file:line' proving it, or remove the number")
        if narr.strip():
            wps = len(narr.split()) / max(float(sc["duration_s"]), 0.1)
            if wps > MAX_WPS:
                add("warn", "narration_pace", sid, f"{len(narr.split())} words in {sc['duration_s']}s ({wps:.1f}/s)",
                    f"shorten the line or raise duration_s: speech fits ~{MAX_WPS}/s (the scene stretches to the audio, but a 12s+ scene reads as a stall)")
            for k, v in say.items():
                if not isinstance(v, str) or not v or str(k).lower() == v.lower():
                    continue
                if v.lower() in narr.lower():  # SRT is cut from the narration: phonetics would reach the captions
                    add("error", "phonetic_in_narration", sid, f"narration contains the spoken form '{v}'",
                        f"write '{k}' in scene.narration and keep '{v}' only in spec.say: captions show the narration text")
            for tok in _spoken_tokens(narr, sc):
                if tok not in say:  # tts.pronounce matches the key exactly, so the lint must too
                    add("warn", "say_missing", sid, f"'{tok}' will be read by the TTS engine",
                        f"add spec.say['{tok}'] = '<how to say it>' (e.g. 'L D preload'), spelled exactly as the token")
    return f


def persist(spec: dict) -> str:
    h = spec_hash(spec)
    d = config.WORK / "specs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{h}.json").write_text(json.dumps(normalize(spec), indent=1))
    return h


def load(h: str) -> dict:
    p = config.WORK / "specs" / f"{h}.json"
    if not p.exists():
        raise FileNotFoundError(f"spec {h} not found: run validate_spec first")
    return json.loads(p.read_text())


def capture_meta(capture_id: str) -> dict:
    """How a capture was taken (tool, aspect, geometry); written by the capture tools next to the
    pixels, so a spec can be audited for format without re-running anything."""
    p = config.WORK / "captures" / capture_id / "capture.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _capture_of(sc: dict) -> tuple[str | None, str]:
    """The capture a scene shows and the field that points at it."""
    if sc.get("capture_id"):
        return str(sc["capture_id"]), "capture_id"
    for key in ("video", "poster", "image"):
        p = sc.get(key)
        if isinstance(p, str) and "captures" in Path(p).parts:
            parts = Path(p).parts
            i = len(parts) - 1 - parts[::-1].index("captures")
            if i + 1 < len(parts) - 1:
                return parts[i + 1], key
    return None, ""


def recaptures(spec: dict, aspect: str) -> list[dict]:
    """Captures the new format cannot reuse, with the call that would redo them."""
    want = fmt(aspect)
    calls = {
        "capture_web": {"aspect": aspect, "viewport": want["viewport"],
                        "device_scale_factor": want["device_scale_factor"]},
        "capture_terminal_session": {"aspect": aspect, "cols": want["cols"], "rows": want["rows"],
                                     "font_size": want["font"]},
        "capture_gui": {"aspect": aspect, "size": want["gui"]},
        "capture_terminal": {"aspect": aspect, "cols": want["max_cols"]},
    }
    out, seen = [], set()
    for sc in spec.get("scenes") or []:
        cid, key = _capture_of(sc)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        m = capture_meta(cid)
        have = m.get("aspect")
        if have == aspect:
            continue
        tool = m.get("tool") or "unknown"
        out.append({"capture_id": cid, "scene": sc.get("id"), "field": key, "tool": tool, "have": have,
                    "reason": f"captured for {have}, not {aspect}" if have else
                              "no capture metadata (format unknown), assume wrong",
                    "redo_with": calls.get(tool, {"aspect": aspect})})
    return out


def _clip(line: str, cols: int) -> str:
    return line if len(line) <= cols else line[:cols - 1].rstrip() + "…"


def reformat(spec: dict, aspect: str) -> dict:
    """Clone a spec into another aspect and apply that format's rules.

    The edits are lossy (bullets dropped, terminal lines trimmed), so every one of them is reported
    instead of applied silently; `recaptures` lists the captures whose geometry no longer matches.
    """
    fmt(aspect)
    s = normalize(spec)
    s["aspect"] = aspect
    cols = FORMATS[aspect]["max_cols"]
    max_bullets = PORTRAIT["max_bullets"] if aspect == "9:16" else 0
    changes = []
    for sc in s["scenes"]:
        ty, sid = sc.get("type"), sc.get("id")
        items = sc.get("items")
        if ty == "bullets" and max_bullets and isinstance(items, list) and len(items) > max_bullets:
            sc["items"] = items[:max_bullets]
            changes.append({"scene": sid, "field": "items",
                            "detail": f"{len(items)} bullets -> {max_bullets} (portrait has no room)",
                            "dropped": items[max_bullets:]})
        lines = sc.get("lines")
        if ty == "terminal" and isinstance(lines, list) and lines:
            cut = [_clip(str(ln), cols) for ln in lines]
            if cut != [str(ln) for ln in lines]:
                changes.append({"scene": sid, "field": "lines",
                                "detail": f"trimmed to {cols} cols",
                                "dropped": [str(ln) for ln in lines if len(str(ln)) > cols]})
                sc["lines"] = cut
    return {"spec": s, "changes": changes, "recaptures": recaptures(s, aspect)}
