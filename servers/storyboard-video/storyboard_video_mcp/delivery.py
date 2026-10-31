"""Delivery bookkeeping: the published name, the CURRENT pointer, one file per review round.

A delivered video is named after what it *is* (`<project>_vNN_<aspect>_<YYYY-MM-DD>.mp4`), never after a
content hash: the user asks for "the 9:16 cut", and two renders of one spec must not become two files
nobody can tell apart. The previous deliveries of the same project and aspect move to `archive/`, and
`CURRENT` (replaced atomically, tmp + os.replace) always points at the last one -- a stale pointer is how
a reviewer signs off a video that is no longer the deliverable.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
from pathlib import Path

from . import config, spec as S
from .safety import safe_path

PROJECT_MAX = 64
NAME_MAX = 120
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")  # no separators, no leading dot, nothing shell-odd
CURRENT = "CURRENT"
NOTES_MAX = 40  # a round is one page: an endless list is a round nobody re-reads
NOTE_TEXT_MAX = 240
TIMECODE_MAX = 24
QUESTION_MAX, DECISION_MAX = 1200, 1200
HASH_MAX, ROUND_MAX = 64, 999
SEVERITIES = ("must", "pref")


class DeliveryError(ValueError):
    """A delivery the folder cannot take. `code` is the finding a caller reports (delivery_exists) and
    `fix` is what the user can do about it."""

    def __init__(self, code: str, message: str, fix: str = ""):
        super().__init__(f"{code}: {message}")
        self.code, self.fix = code, fix


def _root(work: str | Path | None) -> Path:
    return Path(work if work is not None else config.WORK).expanduser().resolve()


def _project_tag(project) -> str:
    """The project is a file name: anything a shell, a glob or a `..` could read as a path is refused."""
    p = str(project or "").strip()
    if not p or len(p) > PROJECT_MAX or not NAME.match(p) or ".." in p:
        raise ValueError(f"project must be a plain name (letters, digits, . _ -, "
                         f"at most {PROJECT_MAX} chars), got {project!r}")
    return p


def _aspect_tag(aspect) -> str:
    s = str(aspect or "").strip().replace(":", "x").replace("×", "x")
    if s not in {a.replace(":", "x") for a in S.ASPECTS}:
        raise ValueError(f"aspect must be one of {sorted(S.ASPECTS)} (got {aspect!r})")
    return s


def _version_tag(version) -> str:
    if isinstance(version, bool):
        raise ValueError(f"version must be a positive integer (got {version!r})")
    if isinstance(version, int):
        n = version
    else:
        m = re.fullmatch(r"[vV]?(\d{1,3})", str(version or "").strip())
        if not m:
            raise ValueError(f"version must be a positive integer like 3 or 'v03' (got {version!r})")
        n = int(m.group(1))
    if not 1 <= n <= ROUND_MAX:
        raise ValueError(f"version must be 1..{ROUND_MAX} (got {n})")
    return f"v{n:02d}"


def _date_tag(date) -> str:
    if isinstance(date, dt.datetime):
        date = date.date()
    if isinstance(date, dt.date):
        return date.isoformat()
    s = str(date or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError(f"date must be YYYY-MM-DD (got {date!r})")
    try:
        return dt.date.fromisoformat(s).isoformat()  # rejects 2026-02-30 and friends
    except ValueError:
        raise ValueError(f"date must be a real calendar day, YYYY-MM-DD (got {date!r})") from None


def delivery_name(project, aspect, version, date) -> str:
    """`<project>_vNN_<16x9|9x16>_<YYYY-MM-DD>.mp4`: the name the user sees, so it is validated first."""
    name = f"{_project_tag(project)}_{_version_tag(version)}_{_aspect_tag(aspect)}_{_date_tag(date)}.mp4"
    if len(name) > NAME_MAX:
        raise ValueError(f"delivery name longer than {NAME_MAX} chars: {name!r}")
    return name


def _previous(d: Path, project: str, aspect: str, keep: str) -> list[Path]:
    """Renders of the same project *and* aspect already in the delivery folder (the other aspect is a
    different deliverable and stays where it is). Matched by regex, not glob: a project name is not a
    pattern."""
    pat = re.compile(rf"{re.escape(project)}_v\d+_{re.escape(aspect)}_\d{{4}}-\d{{2}}-\d{{2}}\.mp4")
    return sorted(p for p in d.iterdir() if p.is_file() and p.name != keep and pat.fullmatch(p.name))


def _point(d: Path, name: str) -> Path:
    """Point `<d>/CURRENT` at `name` in one step: a reader sees the old delivery or the new one, never a
    half-written link. A host without symlinks gets a one-line text pointer instead."""
    link, tmp = d / CURRENT, d / f".{CURRENT}.tmp"
    tmp.unlink(missing_ok=True)  # a crashed run may have left a link *or* a file here
    try:
        os.symlink(name, tmp)
    except (OSError, NotImplementedError):
        tmp.write_text(name + "\n")
    os.replace(tmp, link)  # atomic rename: the pointer is never missing, never points at a temp name
    return link


def current(work: str | Path | None = None) -> Path | None:
    """The delivery `CURRENT` points at: None when there is no pointer at all. A dangling one returns the
    path it names, so a caller can see the video it expected is missing."""
    link = _root(work) / "deliveries" / CURRENT
    try:
        if link.is_symlink():
            return (link.parent / os.readlink(link)).resolve()
        name = link.read_text().strip()  # the text-pointer fallback
    except OSError:
        return None
    return (link.parent / name).resolve() if name else None


def deliver(project, aspect, version, date, src_mp4, work: str | Path | None = None) -> dict:
    """Publish a render under its human name in `/work/deliveries/`.

    Copies (never moves) `src_mp4` to `<project>_vNN_<aspect>_<date>.mp4` via a temp file + rename, so a
    half-copied video is never visible; ships the render's `.srt` (and `CREDITS.txt`, when present) beside
    it; archives the previous deliveries of the same project and aspect; then moves `CURRENT` to the new
    file. A name that already exists is refused (`delivery_exists`): a published video is never edited in
    place. Returns {name, video, srt, credits, current, archived, bytes}.
    """
    root = _root(work)
    project, aspect = _project_tag(project), _aspect_tag(aspect)
    name = delivery_name(project, aspect, version, date)
    src = safe_path(src_mp4, [root, config.REPO])
    if not src.is_file():
        raise FileNotFoundError(f"no render to deliver at {src}")
    d = root / "deliveries"
    dest = d / name
    if src == dest:
        raise ValueError(f"{src} is already the delivery it would be copied to")
    if dest.exists():
        raise DeliveryError("delivery_exists", f"{dest} is already a delivery of {project} {aspect}",
                            fix=f"bump version: publish this cut as v{int(_version_tag(version)[1:]) + 1:02d}")
    d.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        shutil.copyfile(src, tmp)  # copy2 would carry the render's mtime: the delivery date is in the name
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)  # a failed copy leaves no `.part` behind to be reviewed or archived
    srt = src.with_suffix(".srt")
    if srt.is_file():  # every delivery ships subtitles: a promo is also watched muted
        shutil.copyfile(srt, dest.with_suffix(".srt"))
    credits = src.parent / "CREDITS.txt"
    if credits.is_file():  # the credit is the licence condition (CC BY), so it travels with the video
        shutil.copyfile(credits, d / "CREDITS.txt")
    archived = []
    a = d / "archive"
    for p in _previous(d, project, aspect, name):
        a.mkdir(exist_ok=True)
        t = a / p.name
        t.unlink(missing_ok=True)  # same name = same delivery re-published: the newer copy wins
        p.replace(t)
        archived.append(str(t))
    return {"name": name, "video": str(dest),
            "srt": str(dest.with_suffix(".srt")) if srt.is_file() else None,
            "credits": str(d / "CREDITS.txt") if credits.is_file() else None,
            "current": str(_point(d, name)), "archived": archived, "bytes": dest.stat().st_size}


def _clip(s, n: int, keep_lines: bool = False) -> str:
    """Bounded text: a round page is read at a glance, and an unbounded paste is how it stops being one."""
    t = str(s if s is not None else "")
    t = t.strip() if keep_lines else re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _timecode(tc) -> str:
    if isinstance(tc, (int, float)) and not isinstance(tc, bool):
        return f"{float(tc):.1f}s"
    return _clip(re.sub(r"[`\r\n]", " ", str(tc if tc is not None else "")), TIMECODE_MAX) or "-"


def round_log(work, n, question, notes=None, decision="", hash_before="", hash_after="") -> str:
    """Write `/work/rounds/<n>.md`: the question, the notes (timecode + must/pref), the decision and the
    spec_hash before/after. One file per round, rewritten as the round evolves -- never an attachment."""
    root = _root(work)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= ROUND_MAX:
        raise ValueError(f"round number must be 1..{ROUND_MAX} (got {n!r})")
    p = safe_path(root / "rounds" / f"{n}.md", [root])  # the number is an int: no path can be smuggled in
    rows = []
    for e in list(notes or [])[:NOTES_MAX]:
        if not isinstance(e, dict):
            raise ValueError(f"note must be {{timecode, severity, text}}, got {e!r}")
        sev = _clip(e.get("severity"), 16).lower()
        if sev not in SEVERITIES:
            raise ValueError(f"note severity must be one of {SEVERITIES} (got {e.get('severity')!r})")
        text = _clip(e.get("text"), NOTE_TEXT_MAX) or "(no text)"
        rows.append(f"- `{_timecode(e.get('timecode'))}` **{sev}** {text}")
    body = [
        f"# Round {n}", "",
        f"**Question:** {_clip(question, QUESTION_MAX) or '(none)'}", "",
        "**Notes:**", *(rows or ["- (none)"]), "",
        f"**Decision:** {_clip(decision, DECISION_MAX, keep_lines=True) or '(open)'}", "",
        f"`spec_hash` before: `{_clip(hash_before, HASH_MAX) or '-'}`",
        f"`spec_hash` after: `{_clip(hash_after, HASH_MAX) or '-'}`",
    ]
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("\n".join(body) + "\n")
    tmp.replace(p)
    return str(p)


def _library(spec: dict) -> tuple[dict | None, list[dict]]:
    """The music track and the library effects this spec plays: the two things that need a licence."""
    music = spec.get("music") if isinstance(spec.get("music"), dict) else None
    fx = [e for sc in spec.get("scenes") or [] if isinstance(sc, dict)
          for e in sc.get("sfx") or [] if isinstance(e, dict) and e.get("path")]
    return music, fx


def _findings(*items) -> list[dict]:
    return [{"severity": sev, "code": code, "message": msg, "fix": fix} for sev, code, msg, fix in items]


def delivery_check(spec: dict, video_dir: str | Path | None = None) -> list[dict]:
    """What a published file must carry, as findings: subtitles next to the video, `CREDITS.txt` when the
    spec plays library music or effects, and a licence the promo can actually use. Empty list = shippable."""
    d = Path(video_dir).expanduser() if video_dir else None
    out = []
    subs = [p for p in d.glob("*.srt") if p.is_file() and p.stat().st_size > 0] if d else []
    if d is not None and not subs:
        out += _findings(("error", "srt_missing", f"no .srt next to the video in {d}",
                          "re-render: every delivery ships subtitles, a promo is also watched muted"))
    music, fx = _library(spec)
    if (music and music.get("path")) or fx:
        credits = ([d / "CREDITS.txt"] if d else []) + [config.WORK / "CREDITS.txt"]
        if not any(_has_text(p) for p in credits):
            out += _findings(("error", "credits_missing", f"no CREDITS.txt in {d or config.WORK}",
                              "re-render (audio.write_credits writes it next to the video) or paste the "
                              "music-search credit block into the published description"))
    lic = music.get("license") if music else None
    if music and (music.get("path") or lic):
        verdict = S.music_verdict(str(lic or ""))
        if not str(lic or "").strip():
            out += _findings(("error", "music_license_missing", f"music {music.get('path')!r} has no licence",
                              "use the licence string the music-search skill reported (CC0, public domain or CC BY)"))
        elif verdict == "deny":
            out += _findings(("error", "music_license_incompatible", f"licence {lic!r} cannot be published",
                              "commercial promo and syncing is an adaptation: use CC0, public domain or CC BY"))
        elif verdict == "attribution" and not str(music.get("attribution") or "").strip():
            out += _findings(("error", "music_license_missing", f"{lic} needs an attribution and there is none",
                              "paste the credit string the music-search skill returned"))
    for e in fx:
        if S.music_verdict(str(e.get("license") or "")) != "allow":
            out += _findings(("error", "sfx_license_incompatible", f"sfx {e.get('path')!r} is not CC0/PD",
                              "library effects must be CC0 or public domain; anything else is synthesised instead"))
    return out


def _has_text(p: Path) -> bool:
    try:
        return bool(p.read_text().strip())
    except OSError:
        return False
