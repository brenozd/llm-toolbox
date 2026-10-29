"""Bundled music bed: CC0 / public-domain tracks shipped in the image with music/catalog.json.

The catalog is written by scripts/fetch_music.py, which refuses anything not licensed CC0 or public
domain -- so a track id in a spec is either bundled and legally safe, or unknown (a lint error).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config


def _dir() -> Path:
    return Path(config.MUSIC)


def catalog() -> dict:
    try:
        return json.loads((_dir() / "catalog.json").read_text())
    except (OSError, ValueError):
        return {"tracks": []}


def tracks(mood: str | None = None) -> list[dict]:
    """Every bundled track, or only those tagged with `mood` (case-insensitive substring of a tag)."""
    out = [t for t in catalog().get("tracks") or [] if isinstance(t, dict) and t.get("id")]
    if mood:
        m = str(mood).strip().lower()
        out = [t for t in out if any(m in str(x).lower() for x in t.get("mood") or [])]
    return out


def get(tid: str) -> dict | None:
    return next((t for t in tracks() if t["id"] == tid), None)


def path_of(track: dict) -> Path | None:
    """Absolute path of the audio file, or None when the catalog names a file that is not there."""
    f = track.get("file")
    p = _dir() / str(f) if f else None
    return p if p and p.is_file() else None


def list_music(mood: str | None = None) -> dict:
    found = tracks(mood)
    return {"status": "ok", "music_dir": str(_dir()), "mood": mood,
            "tracks": [{"id": t["id"], "title": t.get("title"), "artist": t.get("artist"),
                        "mood": t.get("mood") or [], "duration_s": t.get("duration_s"),
                        "license": t.get("license"), "license_url": t.get("license_url"),
                        "attribution_required": bool(t.get("attribution_required")),
                        "available": path_of(t) is not None} for t in found],
            "moods": sorted({str(x) for t in tracks() for x in t.get("mood") or []})}
