#!/usr/bin/env python3
"""Populate music/ with the bundled soundtrack: download each track from its fixed URL, check the
sha256, and refuse anything whose license is not CC0 or public domain.

Run it once from servers/promo-video (`python scripts/fetch_music.py`). It writes
music/catalog.json -- which is what the MCP server reads -- and music/CREDITS.txt, but only when a
track actually requires attribution (every bundled track here is CC0/PD, so it usually writes none).
Adding a track means adding an entry to TRACKS, with the license and the origin page you read it on.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

MUSIC = Path(__file__).resolve().parent.parent / "music"
LICENSES = {"CC0", "PD"}  # the only two families this bundle ships
ALIASES = {"cc0": "CC0", "cc0 1.0": "CC0", "public domain": "PD", "pd": "PD",
           "public domain mark 1.0": "PD"}  # NOT cc-by*, sa, nc, nd, oga-by: those impose terms
UA = "promo-video-mcp/0.1 (music fetch; https://github.com/brenozd/llm-toolbox)"

# Verified by fetching the origin page: license field read on the page, duration from the file record
# (Wikimedia `imageinfo` / Internet Archive item metadata), then confirmed again with ffprobe locally.
TRACKS = [
    {"id": "moonlight-sonata", "file": "moonlight-sonata.ogg",
     "title": "Moonlight Sonata — Piano Sonata No. 14, 1st mvt (Adagio sostenuto)",
     "artist": "Ludwig van Beethoven (composer); rendering by ComputerHotline (Mutopia MIDI)",
     "license": "PD", "license_note": "Wikimedia Commons: LicenseShortName/UsageTerms 'Public domain', AttributionRequired: false",
     "source_url": "https://commons.wikimedia.org/wiki/File:Moonlight_Sonata.ogg", "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
     "download_url": "https://upload.wikimedia.org/wikipedia/commons/d/d0/Moonlight_Sonata.ogg",
     "sha256": "670ba2019519e4930d57cf7dc6d46261b0a60dd0d776aedd398befd34a39daa9",
     "mood": ["calm", "melancholic", "contemplative"], "duration_s": 306.672,
     "attribution_required": False, "attribution": ""},
    {"id": "hallelujah-chorus-1916", "file": "hallelujah-chorus-1916.ogg",
     "title": "Messiah — Hallelujah Chorus (1916 Edison Diamond Disc)",
     "artist": "G. F. Handel (composer); Edison Diamond Disc recording",
     "license": "PD", "license_note": "Wikimedia Commons: permission 'Public Domain', LicenseShortName 'Public domain', PD US",
     "source_url": "https://commons.wikimedia.org/wiki/File:Messiah_Hallelujah_Chorus_1916.ogg", "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
     "download_url": "https://upload.wikimedia.org/wikipedia/commons/9/90/Messiah_Hallelujah_Chorus_1916.ogg",
     "sha256": "4db921a670837777588541076f43736a6693fc339e0486c205c6f9cc531b9dfd",
     "mood": ["epic", "triumphant", "ceremonial"], "duration_s": 222.955,
     "attribution_required": False, "attribution": ""},
    {"id": "sultana-1908", "file": "sultana-1908.ogg",
     "title": "Sultana (choro, 1908)",
     "artist": "Chiquinha Gonzaga (composer); Grupo Chiquinha Gonzaga — A. Passos, Tute, N. Alves",
     "license": "PD", "license_note": "Wikimedia Commons: credit/permission 'Public domain' (Brazilian law 9.610 + PD US)",
     "source_url": "https://commons.wikimedia.org/wiki/File:Chiquinha_gonzaga_-_sultana_1908.ogg", "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
     "download_url": "https://upload.wikimedia.org/wikipedia/commons/6/68/Chiquinha_gonzaga_-_sultana_1908.ogg",
     "sha256": "d19eacef5cf160aadef83df126cb9ae17fc36e261e5408f1b96b5f5f0a2ca134",
     "mood": ["playful", "light", "period"], "duration_s": 233.312,
     "attribution_required": False, "attribution": ""},
    {"id": "chopin-mazurka-op17-3", "file": "chopin-mazurka-op17-3.ogg",
     "title": "Mazurka, Op. 17 no. 3 in A-flat major",
     "artist": "Frédéric Chopin (composer); Musopen — The Complete Chopin Collection",
     "license": "CC0", "license_note": "Internet Archive item metadata licenseurl = creativecommons.org/publicdomain/zero/1.0/",
     "source_url": "https://archive.org/details/musopen-chopin", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
     "download_url": "https://archive.org/download/musopen-chopin/Mazurka%20Op.%2017%20no.%203%20in%20A%20flat%20major.ogg",
     "sha256": "0af6e6c924c6a61a9304407b619d241d7f2bec69969791aae815cdbcbc9fb37d",
     "mood": ["elegant", "gentle", "wistful"], "duration_s": 246.718,
     "attribution_required": False, "attribution": ""},
    {"id": "chill-main-menu", "file": "chill-main-menu.ogg",
     "title": "Chill Main Menu music",
     "artist": "Augmentality (Brandon Morris), submitted by HaelDB",
     "license": "CC0", "license_note": "OpenGameArt lists CC0 among the item's licenses; CC0 elected (the OGA-BY arm is not relied on)",
     "source_url": "https://opengameart.org/content/chill-main-menu-music", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
     "download_url": "https://opengameart.org/sites/default/files/zombie%20main%20music.ogg",
     "sha256": "5d361c0b2034112c51779ed31e1743718743d4ec9d710a08fc8347d334c7f7e2",
     "mood": ["ambient", "electronic", "modern", "chill"], "duration_s": 99.0,
     "attribution_required": False, "attribution": ""},
]

FIELDS = ("id", "file", "title", "artist", "license", "license_note", "license_url", "source_url",
          "sha256", "mood", "duration_s", "attribution_required", "attribution")


def normalize_license(raw: str) -> str:
    """Map a declared license to CC0|PD, or raise: the bundle ships nothing that needs crediting."""
    key = str(raw or "").strip().lower()
    if key in ALIASES:
        return ALIASES[key]
    raise ValueError(f"license {raw!r} is not CC0 or public domain "
                     f"(allowed: {sorted(LICENSES)}); refusing to bundle it")


def check_track(track: dict) -> dict:
    """Validate one manifest entry without touching the network."""
    # The licence page is what a human re-checks: default it to the origin page rather than leave a
    # track without one, and CC0/PD never needs a credit unless the entry says otherwise.
    track = {"attribution_required": False, "license_url": track.get("source_url") or "", **track}
    missing = [k for k in FIELDS if k not in track]
    if missing:
        raise ValueError(f"track {track.get('id')!r} missing {missing}")
    lic = normalize_license(track["license"])
    sha = str(track["sha256"]).lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError(f"track {track['id']!r} has no valid sha256")
    if not str(track["source_url"]).startswith("https://"):
        raise ValueError(f"track {track['id']!r} needs an https source_url (the origin page)")
    return {**track, "license": lic}


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)


def fetch(track: dict, dest: Path, download=_download) -> Path:
    """Dest already holding the right bytes is left alone (re-running costs no bandwidth)."""
    want = track["sha256"].lower()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == want:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    download(track["download_url"], tmp)
    got = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if got != want:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"{track['id']}: sha256 mismatch (got {got})")
    tmp.replace(dest)
    return dest


def credits(entries: list) -> str:
    """Only tracks that require attribution get a credit line; CC0/PD ones are not listed."""
    rows = [e for e in entries if e.get("attribution_required")]
    if not rows:
        return ""
    lines = ["Music credits", ""]
    for e in rows:
        lines += [f"{e['title']} — {e['artist']}", f"  {e['attribution']}"]
        lines += [f"  {e['source_url']}", ""] if e.get("source_url") else [""]
    return "\n".join(lines)


def build(tracks=None, music: Path = MUSIC, download=_download) -> dict:
    """Download+verify every track whose license is CC0/PD, write catalog.json, and drop anything
    else into `rejected` (never into the catalog)."""
    music = Path(music)
    ok, rejected = [], []
    for track in tracks if tracks is not None else TRACKS:
        try:
            t = check_track(track)
            if download is not None:
                fetch(t, music / t["file"], download)
            ok.append(t)
        except (ValueError, OSError) as e:
            rejected.append({"id": track.get("id"), "reason": str(e)})
    if download is not None:
        music.mkdir(parents=True, exist_ok=True)
        cat = {"version": 1, "licenses": sorted(LICENSES),
               "tracks": [{k: t[k] for k in FIELDS} for t in ok]}
        (music / "catalog.json").write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n")
        text = credits(ok)
        (music / "CREDITS.txt").unlink(missing_ok=True)  # stale credits are worse than none
        if text:
            (music / "CREDITS.txt").write_text(text)
    total = sum((music / t["file"]).stat().st_size for t in ok if (music / t["file"]).is_file())
    return {"status": "ok" if ok else "error", "registered": [t["id"] for t in ok],
            "rejected": rejected, "tracks": len(ok), "total_bytes": total, "music_dir": str(music)}


def main() -> int:
    res = build()
    for r in res["rejected"]:
        print(f"rejected {r['id']}: {r['reason']}", file=sys.stderr)
    print(json.dumps({k: v for k, v in res.items() if k != "rejected"}, indent=1))
    print(f"{res['tracks']} tracks, {res['total_bytes'] / 1e6:.1f} MB")
    return 0 if res["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
