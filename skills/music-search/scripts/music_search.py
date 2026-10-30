#!/usr/bin/env python3
"""music-search: find, license-gate, verify, trim and stage a music bed for promo-video.

python3 stdlib only, plus the host's ffmpeg/ffprobe.

  music_search.py search --vibe "calm ambient" [--source openverse|ia|ccmixter|commons]
                        [--min-s N] [--limit N] [--refresh]
  music_search.py fetch <candidate-id|url> --duration S [--stage-dir DIR]

The promo-video containers mount $XDG_CACHE_HOME/promo-video/music read-only at /music,
so there is no copy step: `fetch` writes <stage>/<id>.<ext> + <stage>/<id>.json and prints
the spec.music JSON with path_in_container=/music/<file>.

Policy (never send `mix` something you cannot defend): allow = CC0 / PDM / PD original
recording; attribution = CC BY; deny = BY-SA (sync-to-picture is an adaptation, so the
whole video would have to be BY-SA), any NC (a promo is commercial), any ND (we trim),
unknown licenses, PD with a third-party recording, and every Freesound-hosted file.
"""

import argparse
import bisect
import hashlib
import json
import os
import re
from html.parser import HTMLParser
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
# Openverse answers plain curl with Cloudflare 504s, so send a browser-ish UA everywhere.
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
SOURCES = ("openverse", "ia", "ccmixter", "commons")
OK_VERDICTS = ("allow", "attribution")
PD_RECORDING_YEARS = 95  # 17 U.S.C. 1401: first publication + 95y (1923-1946 ran the transition)
START_FLOOR_S = 2.0  # pick_start opens at 1.0 s and closes 1.0 s early: the window needs both
MAX_LRA = 32.0  # LU; above this the track's texture moves too much to sit under a whole video
AUDIO_EXT = {"mp3": "mp3", "ogg": "ogg", "flac": "flac", "wav": "wav", "m4a": "m4a", "mp4": "m4a"}
# Licenses doc s7: only the rights-holder's own upload carries a usable license. `mirror`
# alone is a common track name, so only the explicit claims are markers.
REUPLOAD_RE = re.compile(
    r"\bre-?upload|\bno copyright(?: infringement)? intended\b|\bnot mine\b|\bripped\b"
    r"|\bpromoted upload\b|\bfull album upload\b",
    re.I,
)

# Vibe -> extra tags. Source tags are the only stable ranker (audio features flip top-1
# between windows: see the vibe report), so ranking is a tag intersection, nothing else.
VIBES = {
    "ambient": ["ambient", "atmosphere", "atmospheric", "drone", "soundscape", "relaxing"],
    "calm": ["calm", "chill", "chillout", "soft", "mellow", "peaceful", "downtempo", "relaxing"],
    "tech": ["technology", "electronic", "synth", "synthesizer", "cyberpunk", "computer", "idm"],
    "epic": ["epic", "trailer", "cinematic", "orchestral", "dramatic", "powerful", "heroic"],
    "playful": ["playful", "upbeat", "happy", "fun", "quirky", "bouncy", "energetic"],
    "elegant": ["elegant", "piano", "classical", "minimal", "acoustic", "gentle"],
}

# License signatures, most specific first: a bare "licenses/by" is a prefix of by-sa,
# by-nc, by-nd, so the long forms must win the scan.
SIGNATURES = (
    ("by-nc-nd", ("by-nc-nd", "byncnd", "by_nc_nd")),
    ("by-nc-sa", ("by-nc-sa", "byncsa", "by_nc_sa")),
    ("by-nc", ("by-nc", "bync", "by_nc")),
    ("by-nd", ("by-nd", "bynd", "by_nd")),
    ("by-sa", ("by-sa", "bysa", "by_sa")),
    ("cc0", ("zero/1.0", "publicdomain/zero", "cc0", "cc-zero", "cc zero", "cczero")),
    ("pdm", ("publicdomain/mark", "public-domain-mark", "public domain mark", "pdm",
            "licenses/publicdomain")),  # legacy CC PD dedication: a dedication about the file
    ("by", ("licenses/by", "creativecommons.org/by", "/by/", "cc by", "cc-by")),
    ("pd", ("public domain", "publicdomain", " pd ")),
)
# Denials that no origin page can repair; anything else gets a second look at the origin.
FATAL_REASONS = {
    "freesound_preview_tos",
    "non_commercial_license",
    "no_derivatives_license",
    "share_alike_sync",
    "pd_composition_third_party_recording",
    "reupload_or_mirror",
}
LICENSE_NAME = {
    "by": "CC BY",
    "by-sa": "CC BY-SA",
    "by-nc": "CC BY-NC",
    "by-nd": "CC BY-ND",
    "by-nc-sa": "CC BY-NC-SA",
    "by-nc-nd": "CC BY-NC-ND",
}
CANON_URL = {
    "cc0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "pdm": "https://creativecommons.org/publicdomain/mark/1.0/",
}


# --------------------------------------------------------------------------- io


def http_get(url, *, timeout=25, tries=3, binary=False, referer=None):
    """The single network door (tests replace this function).

    One shot is not enough: api.openverse.org times out behind Cloudflare and
    archive.org's search backend returns transient 200s with an error body.
    ccMixter serves files only with a Referer, so pass the landing page.
    """
    err = None
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return raw if binary else raw.decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            err = exc
            if i + 1 < tries:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET {url} failed after {tries} tries: {err}")


def get_json(url, *, tries=3, **kw):
    """archive.org answers 200 with {"error": "[BACKEND_ERROR] ..."} while Elasticsearch
    is busy; retry, and never let an error body look like an empty result set (which
    would then get cached as "no results" for a day)."""
    data = {}
    for i in range(tries):
        data = json.loads(http_get(url, **kw))
        if not (isinstance(data, dict) and data.get("error")):
            return data
        if i + 1 < tries:
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"error payload from {url}: {data.get('error')}")


def cache_root():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "promo-video"


def default_stage():
    return cache_root() / "music"


def cached(key, producer, *, refresh=False, ttl=86400):
    """On-disk cache: Openverse anon quota is 20/min and 200/day."""
    path = cache_root() / "search" / (slug(key) + ".json")
    if not refresh and path.is_file() and time.time() - path.stat().st_mtime < ttl:
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    data = producer()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def slug(text, limit=60):
    out = re.sub(r"[^a-z0-9._-]+", "-", str(text).lower())
    out = re.sub(r"-{2,}", "-", out).strip("-._")
    return out[:limit].strip("-._") or "x"


# --------------------------------------------------------------------- licenses


def parse_license(raw="", *, url="", version=""):
    """-> (license id, version). Aggregators hand out tokens ("cc0"), URLs (IA) and
    names ("CC0 (CC Zero)"), so scan all three."""
    text = " ".join(str(x) for x in (raw, url, version) if x).lower().replace("_", "-")
    token = str(raw or "").strip().lower()
    if token in ("cc0", "pdm", "pd", "by", "by-sa", "by-nd", "by-nc", "by-nc-sa", "by-nc-nd"):
        ver = str(version or "").strip()
        return token, ver if re.match(r"^\d\.\d$", ver) else _version_from(url, token)
    for name, needles in SIGNATURES:
        if any(n in text for n in needles):
            return name, _version_from(url or text, name, version)
    return "other", ""


def _version_from(text, lic, version=""):
    if lic in ("cc0", "pdm"):
        return str(version or "1.0") if lic == "pdm" else "1.0"
    if re.match(r"^\d\.\d$", str(version or "")):
        return str(version)
    m = re.search(r"/(\d\.\d)(?:/|$|\s)", str(text))
    if m:
        return m.group(1)
    m = re.search(r"\b(\d\.\d)\b", str(text))  # text-only node: "CC BY 3.0"
    return m.group(1) if m else ""  # never invent a version: policy refuses an unknown one


def license_label(lic, version=""):
    if lic == "cc0":
        return "CC0 1.0"
    if lic == "pdm":
        return "Public Domain Mark 1.0"
    if lic == "pd":
        return "Public domain"
    if lic in LICENSE_NAME:
        return f"{LICENSE_NAME[lic]} {version}".strip()
    return "OTHER"


def license_url_for(lic, version=""):
    if lic in CANON_URL:
        return CANON_URL[lic]
    if lic in LICENSE_NAME:
        return f"https://creativecommons.org/licenses/{lic}/{version + '/' if version else ''}"
    return ""


def pd_cutoff(today=None):
    """US recordings enter the public domain 95 years after first publication, and the
    cutoff moves every 1 January - never hardcode 1923-1946."""
    return (today or date.today()).year - PD_RECORDING_YEARS


def policy(cand, *, today=None):
    """License -> verdict. `verdict` is the only field `mix` may trust, so it is always
    recomputed from the license evidence, never copied from the source."""
    today = today or date.today()
    lic = cand.get("license_id") or "other"
    ver = cand.get("license_version") or ""
    if ver and not re.match(r"^\d\.\d$", str(ver)):
        ver = ""  # an unparsable version is an unknown version, not a guess
    host = str(cand.get("host") or "").lower()
    provider = str(cand.get("provider") or "").lower()
    cutoff = pd_cutoff(today)
    year = cand.get("published_year")
    original = cand.get("original_transfer", True)
    out = {
        "license": license_label(lic, ver),
        "license_id": lic,
        "license_version": ver,
        "license_url": cand.get("license_url") or license_url_for(lic, ver),
        "attribution_required": lic in LICENSE_NAME,
        "recording_is_original_transfer": bool(original),
    }
    if cand.get("reupload"):
        # Licenses doc s7: a rights field on a reupload/mirror channel proves nothing.
        out.update(verdict="deny", verdict_reason="reupload_or_mirror")
        out["jurisdiction_note"] = "Origin is a reupload/mirror channel, not the rights-holder: refuse."
    elif "freesound" in host or provider == "freesound":
        # Freesound's API ToS forbids using its content outside the Freesound application;
        # Openverse audio is ~100% Freesound previews on cdn.freesound.org, so skip them.
        out.update(verdict="deny", verdict_reason="freesound_preview_tos")
        out["jurisdiction_note"] = "Freesound ToS: API content may not be used outside their app."
    elif lic == "cc0":
        out.update(verdict="allow", verdict_reason="cc0_waives_copyright_and_neighbouring_rights")
        out["jurisdiction_note"] = "CC0 1.0 waives copyright and related rights worldwide; no endorsement implied."
    elif lic == "pdm":
        out.update(verdict="allow", verdict_reason="public_domain_mark")
        out["jurisdiction_note"] = "PDM is a label, not a license: the file is declared free of known restrictions."
    elif lic == "pd":
        confirmed = cand.get("published_year_source") in ("metadata", "extmetadata")
        if not original:
            out.update(verdict="deny", verdict_reason="pd_composition_third_party_recording")
        elif year is None:
            out.update(verdict="deny", verdict_reason="pd_recording_year_unknown")
        elif not confirmed:
            # An uploader's own year field is a claim; only the item's metadata dates it.
            out.update(verdict="deny", verdict_reason=f"pd_recording_year_unconfirmed_{year}")
        elif int(year) >= cutoff:
            out.update(verdict="deny", verdict_reason=f"pd_recording_not_expired_{year}_cutoff_{cutoff}")
        else:
            out.update(verdict="allow", verdict_reason=f"pd_recording_published_{year}_before_{cutoff}")
        out["jurisdiction_note"] = (
            f"US: recordings first published before {cutoff} are PD (95y rule, computed "
            f"{today.year}); EU/UK: phonogram term 70y from publication. A remastered "
            f"reissue can carry a new phonogram right."
        )
    elif "nc" in lic:
        out.update(verdict="deny", verdict_reason="non_commercial_license")
        out["jurisdiction_note"] = "A product promo is commercial; NC is not waivable by 'no ads'."
    elif "nd" in lic:
        out.update(verdict="deny", verdict_reason="no_derivatives_license")
        out["jurisdiction_note"] = "Syncing and trimming is a modification; ND forbids it."
    elif "sa" in lic:
        out.update(verdict="deny", verdict_reason="share_alike_sync")
        out["jurisdiction_note"] = "Sync-to-picture is Adapted Material, so the whole video would be BY-SA."
    elif lic in LICENSE_NAME:
        # 3.0/4.0 are the terms we know how to credit; older ports and an unknown version
        # are refused, and 4.0 is never assumed (the sidecar must say what the page said).
        if not ver:
            out.update(verdict="deny", verdict_reason="cc_by_version_unknown")
            out["jurisdiction_note"] = "No CC BY version at the origin, so no version's terms: refuse."
        elif float(ver) < 3.0:
            out.update(verdict="deny", verdict_reason=f"cc_by_{ver}_unsupported")
            out["jurisdiction_note"] = "CC BY 2.5 and older are jurisdictional ports, not the 3.0/4.0 terms: refuse."
        else:
            out.update(verdict="attribution", verdict_reason=f"cc_by_{ver}_needs_credit")
            out["jurisdiction_note"] = "Commercial use OK; credit, license link and changes note are mandatory."
    else:
        out.update(verdict="deny", verdict_reason="license_unknown")
        out["jurisdiction_note"] = "No usable license string at the origin: refuse."
    out["content_id_risk"] = content_id_risk(cand, lic, year, cutoff)
    return out


def content_id_risk(cand, lic, year, cutoff):
    if lic in ("cc0", "pdm") and cand.get("source") in ("ia", "ccmixter", "commons"):
        return "low"
    if lic == "pd" or (year and int(year) < cutoff):
        return "high"  # PD-era discs reissued by a label are the classic Content ID claim
    return "medium"


def attribution_block(track, changes="trimmed and synced to video, no other edits"):
    """CC BY 4.0 s3(a)(1)(A)-(E) wants creator, copyright notice, license name+URI,
    material URI and a changes note; one block covers all five."""
    lic = track.get("license") or license_label(track.get("license_id", "other"))
    url = track.get("license_url") or license_url_for(track.get("license_id", "other"))
    lines = [f'"{track.get("title") or "Untitled"}" by {track.get("creator") or "Unknown creator"} - {lic}']
    if track.get("copyright"):
        lines.append(f"Copyright: {track['copyright']}")
    lines.append(f"Source: {track.get('source_url') or 'n/a'} - License: {url}")
    lines.append(f"Changes: {changes}.")
    lines.append(
        track.get("disclaimer")
        or "Provided as-is, without warranty of any kind; no endorsement by the creator is implied."
    )
    return " | ".join(lines)


# ----------------------------------------------------------------------- search


def vibe_tags(vibe):
    words = re.findall(r"[a-z0-9]+", str(vibe).lower())
    tags = set(words)
    for name, extra in VIBES.items():
        if name in words or any(w.startswith(name[:4]) for w in words):
            tags.update(extra)
    return tags


def vibe_score(cand, tags):
    mood = {str(t).lower() for t in cand.get("mood") or []}
    title = str(cand.get("title") or "").lower()
    return len(mood & tags) + sum(1 for w in tags if w in title)


def _cand(**kw):
    cand = {
        "id": "",
        "source": "",
        "provider": "",
        "host": "",
        "title": "",
        "creator": "",
        "license_id": "other",
        "license_version": "",
        "license_url": "",
        "source_url": "",
        "file_url": "",
        "duration_s": None,
        "mood": [],
        "seed_attribution": "",
        "published_year": None,
        "published_year_source": "",  # "metadata"|"extmetadata" = cross-checked; "uploader" = a claim
        "reupload": False,
        "original_transfer": True,
        "copyright": "",
        "disclaimer": "",
    }
    cand.update(kw)
    return cand


def _reupload(*texts):
    """Licenses doc s7: a rights field on a reupload or mirror channel is not evidence."""
    blob = " ".join(str(t or "") for t in texts)
    return bool(REUPLOAD_RE.search(blob))


def search_openverse(vibe, limit, *, refresh=False):
    # license=pdm returns 0 audio items on Openverse (live-check), so PDM rides in from
    # IA/Commons instead of being requested here for nothing.
    query = urllib.parse.urlencode(
        {"q": vibe, "license": "cc0,by", "page_size": str(min(20, max(limit * 4, 10)))}
    )
    url = f"https://api.openverse.org/v1/audio/?{query}"
    data = cached(f"openverse-{vibe}-{limit}", lambda: get_json(url), refresh=refresh)
    out = []
    for r in data.get("results") or []:
        file_url = r.get("url") or ""
        lic, ver = parse_license(r.get("license"), url=r.get("license_url"), version=r.get("license_version"))
        out.append(
            _cand(
                id="ov-" + slug(r.get("id") or file_url, 12),
                source="openverse",
                provider=r.get("source") or r.get("provider") or "",
                host=urllib.parse.urlsplit(file_url).netloc.lower(),
                title=(r.get("title") or "").strip(),
                creator=r.get("creator") or "",
                license_id=lic,
                license_version=ver,
                license_url=r.get("license_url") or license_url_for(lic, ver),
                source_url=r.get("foreign_landing_url") or r.get("detail_url") or "",
                file_url=file_url,
                duration_s=_ms_to_s(r.get("duration")),
                mood=sorted({str(t.get("name", "")).lower() for t in (r.get("tags") or []) if t.get("name")}),
                seed_attribution=r.get("attribution") or "",
                reupload=_reupload(r.get("title")),
            )
        )
    return out


def search_ia(vibe, limit, *, refresh=False):
    # licenseurl is uploader-set, so it is only a claim: fetch re-verifies at /metadata/.
    # Wildcards with a slash (`*licenses/by*`) make archive.org's ES answer BACKEND_ERROR;
    # `*by*` is the same net and stays up.
    words = " OR ".join(w for w in re.findall(r"[a-z0-9]+", vibe.lower()) if len(w) > 2) or vibe
    query = (
        f"({words}) AND mediatype:audio AND "
        f"(licenseurl:*publicdomain* OR licenseurl:*by*)"
    )
    params = [
        ("q", query),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "creator"),
        ("fl[]", "licenseurl"),
        ("fl[]", "subject"),
        ("fl[]", "year"),
        ("rows", str(min(50, max(limit * 3, 10)))),
        ("output", "json"),
    ]
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params)
    data = cached(f"ia-{query}-{limit}", lambda: get_json(url), refresh=refresh)
    docs = ((data.get("response") or {}).get("docs")) or []
    out = []
    for d in docs:
        lic, ver = parse_license(d.get("licenseurl"))
        ident = d.get("identifier") or ""
        subject = d.get("subject") or []
        if isinstance(subject, str):
            subject = re.split(r"[;,]", subject)
        out.append(
            _cand(
                id="ia-" + slug(ident, 50),
                source="ia",
                provider="archive.org",
                host="archive.org",
                title=str(d.get("title") or ident),
                creator=_first(d.get("creator")),
                license_id=lic,
                license_version=ver,
                license_url=d.get("licenseurl") or license_url_for(lic, ver),
                source_url=f"https://archive.org/details/{ident}",
                file_url="",  # resolved per item in fetch: a 1 h item can hold 145 MB files
                ia_id=ident,
                published_year=_year(d.get("year") or d.get("date")),
                # archive.org's `year`/`date` is the uploader's own field, so it is only a
                # claim: fetch re-reads the item metadata and sets published_year_source.
                published_year_source="uploader" if _year(d.get("year") or d.get("date")) else "",
                reupload=_reupload(d.get("title"), " ".join(str(s) for s in subject)),
                original_transfer=not _remastered(" ".join(str(x) for x in (d.get("title"), subject))),
                mood=sorted({str(s).strip().lower() for s in subject if str(s).strip()}),
            )
        )
    return out


def search_ccmixter(vibe, limit, *, refresh=False):
    out = []
    for code in ("zero", "by"):
        params = urllib.parse.urlencode(
            {"datasource": "uploads", "lic": code, "search": vibe, "f": "json", "limit": str(limit)}
        )
        url = f"https://ccmixter.org/api/query?{params}"
        data = cached(f"ccmixter-{code}-{vibe}", lambda: get_json(url), refresh=refresh)
        if isinstance(data, dict):
            data = data.get("records") or data.get("results") or []
        out += [_ccm_cand(item) for item in data]
    return out


def _ccm_cand(item):
    files = item.get("files") or []
    audio = [f for f in files if str((f.get("file_format_info") or {}).get("media-type", "")).startswith("audio")]
    best = sorted(audio, key=lambda f: (str(f.get("file_nicname")) != "mp3", int(f.get("file_rawsize") or 0)))[:1]
    lic, ver = parse_license(item.get("license_name"), url=item.get("license_url"))
    return _cand(
        id="ccm-" + slug(item.get("upload_id")),
        source="ccmixter",
        provider="ccmixter.org",
        host="ccmixter.org",
        title=item.get("upload_name") or "",
        creator=item.get("user_real_name") or item.get("user_name") or "",
        license_id=lic,
        license_version=ver,
        license_url=item.get("license_url") or license_url_for(lic, ver),
        source_url=item.get("file_page_url") or "",
        file_url=(best[0].get("download_url") or "") if best else "",
        duration_s=_clock_to_s((best[0].get("file_format_info") or {}).get("ps") if best else ""),
        mood=sorted({t.strip().lower() for t in str(item.get("upload_tags") or "").split(",") if t.strip()}),
        reupload=_reupload(item.get("upload_name"), item.get("upload_tags")),
        ccm_id=item.get("upload_id"),
        bpm=(item.get("upload_extra") or {}).get("bpm") or 0,
    )


def search_commons(vibe, limit, *, refresh=False):
    params = [
        ("action", "query"),
        ("format", "json"),
        ("generator", "search"),
        ("gsrsearch", f"filetype:audio {vibe}"),
        ("gsrnamespace", "6"),
        ("gsrlimit", str(min(20, max(limit * 2, 5)))),
        ("prop", "imageinfo"),
        ("iiprop", "url|size|extmetadata"),
    ]
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    data = cached(f"commons-{vibe}", lambda: get_json(url), refresh=refresh)
    pages = ((data.get("query") or {}).get("pages") or {}).values()
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        short = _em(meta, "LicenseShortName")
        lic, ver = parse_license(short, url=_em(meta, "LicenseUrl"))
        # Commons keeps the file's own date in extmetadata, so a PD file gets its year here
        # instead of being refused for a missing one.
        year = _year(_em(meta, "DateTimeOriginal") or _em(meta, "DateTime"))
        out.append(
            _cand(
                id="wc-" + slug(str(p.get("title") or ""), 40),
                source="commons",
                provider="wikimedia",
                host="upload.wikimedia.org",
                title=re.sub(r"^File:", "", str(p.get("title") or "")),
                creator=_strip_tags(_em(meta, "Artist")),
                license_id=lic,
                license_version=ver,
                license_url=_em(meta, "LicenseUrl") or license_url_for(lic, ver),
                source_url="https://commons.wikimedia.org/wiki/" + urllib.parse.quote(str(p.get("title") or "")),
                file_url=_clean_url(info.get("url") or ""),
                duration_s=_ms_to_s(float(info.get("duration") or 0) * 1000) if info.get("duration") else None,
                published_year=year,
                published_year_source="extmetadata" if year else "",
                reupload=_reupload(re.sub(r"^File:", "", str(p.get("title") or ""))),
                mood=sorted({w for w in re.findall(r"[a-z]{4,}", str(p.get("title") or "").lower())}),
                wc_title=str(p.get("title") or ""),
                copyright=_strip_tags(_em(meta, "Credit")),
            )
        )
    return out


SEARCHERS = {
    "openverse": search_openverse,
    "ia": search_ia,
    "ccmixter": search_ccmixter,
    "commons": search_commons,
}


def search(vibe, *, source=None, min_s=0, limit=5, refresh=False, today=None):
    """Rank candidates by tag overlap, then drop everything the policy denies.

    No fallback track: an empty pool is a valid answer and the mix stays silent.
    """
    tags = vibe_tags(vibe)
    notes, raw = [], []
    for name in ([source] if source else SOURCES):
        try:
            got = SEARCHERS[name](vibe, limit, refresh=refresh)
            notes.append(f"{name}:{len(got)}")
            raw += got
        except Exception as exc:  # noqa: BLE001 - a dead source is not a dead search
            notes.append(f"{name}:error:{type(exc).__name__}")
    kept, skipped = [], {}
    for cand in raw:
        cand.update(policy(cand, today=today))
        if cand["verdict"] not in OK_VERDICTS:
            skipped[cand["verdict_reason"].split("_cutoff")[0]] = skipped.get(
                cand["verdict_reason"].split("_cutoff")[0], 0
            ) + 1
            continue
        if min_s and cand.get("duration_s") and cand["duration_s"] < min_s:
            skipped["too_short"] = skipped.get("too_short", 0) + 1
            continue
        cand["attribution"] = attribution_block(cand)
        cand["vibe_score"] = vibe_score(cand, tags)
        cand["bpm"] = cand.get("bpm") or 0
        kept.append(cand)
    seen, unique = set(), []
    for cand in sorted(kept, key=lambda c: (-c["vibe_score"], c["source"], c["title"].lower())):
        key = (cand["title"].lower(), cand["creator"].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(cand)
    results = unique[:limit]
    remember(results)
    payload = {
        "vibe": vibe,
        "tags": sorted(tags),
        "count": len(results),
        "results": results,
        "sources": notes,
        "skipped": skipped,
    }
    if not results:
        why = ", ".join(f"{k}x{v}" for k, v in sorted(skipped.items())) or "no candidates"
        payload["reason"] = (
            f"no allow/attribution track for {vibe!r} ({'; '.join(notes)}; skipped {why}) - "
            "keep the mix silent: there is no fallback track."
        )
    return payload


# -------------------------------------------------------------- candidate index


def index_path():
    return cache_root() / "candidates.json"


def load_index():
    try:
        return json.loads(index_path().read_text())
    except (OSError, ValueError):
        return {}


def remember(cands):
    if not cands:
        return
    idx = load_index()
    for cand in cands:
        cand["retrieved_at"] = _now()
        idx[cand["id"]] = cand
    index_path().parent.mkdir(parents=True, exist_ok=True)
    index_path().write_text(json.dumps(idx, indent=1))


def resolve_candidate(target):
    """`fetch` takes a candidate id from `search` or a URL. A bare file URL carries no
    license, so the origin page still has to prove one before anything downloads."""
    index = load_index()
    if target in index:
        return dict(index[target])
    for cand in index.values():
        if target in (cand.get("file_url"), cand.get("source_url")):
            return dict(cand)
    parts = urllib.parse.urlsplit(target)
    host = parts.netloc.lower()
    base = {"source_url": target, "file_url": target, "host": host, "id": "url-" + slug(target.rsplit("/", 1)[-1], 40)}
    if "freesound.org" in host:
        return _cand(**base, source="web", provider="freesound")
    if host == "archive.org" and parts.path.startswith("/download/"):
        ident = parts.path.split("/")[2]
        return _cand(**base, source="ia", provider="archive.org", ia_id=ident,
                     source_url=f"https://archive.org/details/{ident}")
    if "ccmixter.org" in host:
        return _cand(**base, source="ccmixter", provider="ccmixter.org")
    return _cand(**base, source="web")


# ------------------------------------------------------- verify at the origin


def verify_at_origin(cand):
    """Read the rights field on the origin page and quote it. Never download first:
    an aggregator's license field can be stale, wrong, or missing."""
    source = cand.get("source")
    try:
        if source == "ia":
            md = get_json(f"https://archive.org/metadata/{cand.get('ia_id') or cand['id']}")
            meta = md.get("metadata") or {}
            raw = meta.get("licenseurl") or meta.get("license") or ""
            lic, ver = parse_license(raw)
            out = _verified(raw, lic, ver, raw, f'archive.org metadata licenseurl="{raw}"', cand)
            # Cross-check the year: the search result's `year` is the uploader's field, the
            # item metadata is the same claim in a second place - disagree, and we refuse.
            year = _year(meta.get("date") or meta.get("year") or meta.get("publicdate"))
            if out.get("ok") and year and cand.get("published_year") and int(cand["published_year"]) != year:
                return {"ok": False, "detail": f"year conflict: search said {cand['published_year']}, metadata says {year}"}
            if out.get("ok") and year:
                out.update(published_year=year, published_year_source="metadata")
            return out
        if source == "ccmixter":
            params = urllib.parse.urlencode(
                {"datasource": "uploads", "ids": cand.get("ccm_id"), "f": "json"}
            )
            data = get_json(f"https://ccmixter.org/api/query?{params}")
            item = (data[0] if isinstance(data, list) and data else data) or {}
            raw = item.get("license_url") or item.get("license_name") or ""
            lic, ver = parse_license(item.get("license_name"), url=item.get("license_url"))
            return _verified(raw, lic, ver, item.get("license_url") or "", f'ccmixter api license_url="{raw}"', cand)
        if source == "commons":
            title = cand.get("wc_title") or re.sub(r"^File:", "", urllib.parse.unquote(cand["source_url"]).rsplit("/", 1)[-1])
            params = urllib.parse.urlencode(
                {"action": "query", "format": "json", "prop": "imageinfo",
                 "iiprop": "extmetadata", "titles": title}
            )
            data = get_json(f"https://commons.wikimedia.org/w/api.php?{params}")
            page = next(iter(((data.get("query") or {}).get("pages") or {}).values()), {})
            meta = ((page.get("imageinfo") or [{}])[0]).get("extmetadata") or {}
            short, url = _em(meta, "LicenseShortName"), _em(meta, "LicenseUrl")
            lic, ver = parse_license(short, url=url)
            year = _year(_em(meta, "DateTimeOriginal") or _em(meta, "DateTime"))
            return _verified(
                short, lic, ver, url or license_url_for(lic, ver),
                f'commons extmetadata LicenseShortName="{short}" LicenseUrl="{url}"',
                cand,
                extra={
                    "copyright": _strip_tags(_em(meta, "Credit")) or cand.get("copyright", ""),
                    "published_year": year,
                    "published_year_source": "extmetadata" if year else "",
                },
            )
        if source == "openverse" and cand.get("provider") != "freesound":
            page = http_get(cand["source_url"])
            lic, ver = _scan_license(page)
            return _verified(
                lic, lic, ver, license_url_for(lic, ver),
                f"origin page {cand['source_url']} shows license marker {lic!r}", cand, page=page,
            )
        if source == "web":
            page = http_get(cand["source_url"])
            lic, ver = _scan_license(page)
            return _verified(
                lic, lic, ver, license_url_for(lic, ver),
                f"origin page {cand['source_url']} shows license marker {lic!r}", cand, page=page,
            )
        return {"ok": False, "detail": f"no origin check available for source={source!r}"}
    except Exception as exc:  # noqa: BLE001 - unreachable origin == unverified
        return {"ok": False, "detail": f"origin unreachable: {type(exc).__name__}: {exc}"}


def _verified(raw, lic, ver, url, evidence, cand, *, extra=None, page=None):
    if not lic or lic == "other":
        return {"ok": False, "detail": f"origin page shows no usable license ({evidence})"}
    claimed = cand.get("license_id")
    if claimed and claimed not in ("other", lic):
        return {
            "ok": False,
            "detail": f"license mismatch: aggregator said {claimed}, origin says {lic} ({evidence})",
        }
    out = {
        "ok": True,
        "license_id": lic,
        "license_version": ver or cand.get("license_version") or "",
        "license_url": url or cand.get("license_url") or license_url_for(lic, ver),
        "license_evidence": evidence,
        "raw_license": str(raw),
    }
    if extra:
        out.update({k: v for k, v in extra.items() if v})
    if page is not None:
        out["disclaimer"] = _disclaimer_from(page)
    return out


class _LicenseNodes(HTMLParser):
    """Collect markers only from the page's own license node.

    A page-wide text scan licensed an all-rights-reserved file off a stray `/by/` href and a
    site-footer "CC0" (live repro), so accept two shapes only: `<a rel="license">` and
    whatever sits inside an element whose class/id says license/credit/attribution/rights.
    """

    CONTAINER = re.compile(r"licen[cs]e|credit|attribution|rights", re.I)
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.markers = []
        self._open = []  # one flag per open element: are we inside a license node?
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        href = a.get("href") or ""
        rel = (a.get("rel") or "").lower().split()
        if href and ("license" in rel or self._inside()):
            self._buffer.append(href)  # an href is evidence, never page geometry
        if tag not in self.VOID:
            self._open.append(bool(self.CONTAINER.search(f"{a.get('class') or ''} {a.get('id') or ''}")))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID and self._open:
            self._open.pop()

    def handle_endtag(self, tag):
        if tag not in self.VOID and self._open:
            self._open.pop()

    def handle_data(self, data):
        if self._inside():
            self._buffer.append(data)

    def _inside(self):
        return any(self._open)

    def markers_found(self):
        return self._buffer


def _scan_license(page):
    """-> (license id, version) read from the page's license node; 'other' when absent or
    when the nodes disagree (two licenses on one page prove neither)."""
    scan = _LicenseNodes()
    try:
        scan.feed(str(page))
        scan.close()
    except Exception:  # noqa: BLE001 - unparsable html is an unlicensed page
        return "other", ""
    found = {}
    for chunk in scan.markers_found():
        lic, ver = parse_license(chunk)
        if lic != "other" and not found.get(lic):
            found[lic] = ver
    if len(found) != 1:
        return "other", ""
    lic, ver = next(iter(found.items()))
    return lic, ver


def _disclaimer_from(page):
    match = re.search(r"[^<>]{0,120}(?:as is|as-is|no warranty|without warranty)[^<>]{0,160}", page, re.I)
    return re.sub(r"\s+", " ", match.group(0)).strip() if match else ""


# ------------------------------------------------------------------------ fetch


def probe(path):
    """-> (duration_s, container ext) from one ffprobe call."""
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration,format_name",
         "-of", "default=nw=1", str(path)],
        capture_output=True, text=True, timeout=180,
    )
    data = dict(
        line.split("=", 1) for line in out.stdout.splitlines() if "=" in line
    )
    try:
        duration = float(data.get("duration") or 0)
    except ValueError:
        duration = 0.0
    names = str(data.get("format_name") or "").split(",")
    ext = next((AUDIO_EXT[n] for n in names if n in AUDIO_EXT), "mp3")
    return duration, ext


def analyze(path):
    """One ffmpeg pass -> loudness envelope, spectral centroid/rolloff and flux.

    Gating on centroid/rolloff, not flatness: flatness ranked the noisiest fixture lowest
    (0.0031), so it cannot separate a hiss-dominated transfer from a quiet recording.
    """
    cmd = [
        FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-af",
        "aresample=48000,ebur128=metadata=1:peak=none,"
        "aspectralstats=measure=centroid+rolloff+flux,ametadata=mode=print:file=-",
        "-f", "null", "-",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    return parse_analysis(out.stdout)


def parse_analysis(text):
    frames, cur = [], None
    for line in str(text).splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            cur = {"t": 0.0, "m": -120.0, "i": -120.0, "centroid": 0.0, "rolloff": 0.0, "flux": 0.0}
            m = re.search(r"pts_time:([0-9.]+)", line)
            if m:
                cur["t"] = float(m.group(1))
            frames.append(cur)
            continue
        if cur is None or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        try:
            num = float(raw)
        except ValueError:
            continue
        leaf = key.rsplit(".", 1)[-1]
        if key.startswith("lavfi.r128"):
            if leaf in ("M", "I"):
                cur[leaf.lower()] = num
            elif leaf == "LRA":
                cur["lra"] = num
        elif "aspectralstats" in key and leaf in ("centroid", "rolloff", "flux"):
            cur[leaf] = num
    lufs = frames[-1]["i"] if frames else -120.0
    lra = max((f.get("lra", 0.0) for f in frames), default=0.0)
    return {"lufs": lufs, "lra": lra, "frames": frames}


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def gate(analysis):
    """Reject what must never become a bed; None means pass."""
    frames = analysis.get("frames") or []
    if not frames:
        return "no_audio"
    if analysis.get("lufs", -120.0) <= -60.0:
        return "digital_silence"
    if analysis.get("lra", 0.0) > MAX_LRA:
        return "lra_too_high"
    centroid = _median(f["centroid"] for f in frames)
    rolloff = _median(f["rolloff"] for f in frames)
    # Hiss/cicadas put the rolloff near Nyquist; a 78rpm transfer without noise reduction
    # sits low with almost no energy above 2 kHz.
    if rolloff > 12000.0 or centroid > 4000.0:
        return "noise_dominated"
    if centroid < 250.0 and rolloff < 600.0:
        return "too_dark_rumble"
    return None


def flux_peaks(frames, total_s, mind=0.25):
    if not frames:
        return []
    vals = [f["flux"] for f in frames]
    mean = sum(vals) / len(vals)
    spread = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    peaks, last = [], -1e9
    for f in frames:
        if f["flux"] > mean + spread and f["t"] - last >= mind:
            peaks.append(f["t"])
            last = f["t"]
    return peaks


def pick_start(analysis, total_s, want_s):
    """Window whose onset rate and level are closest to the track medians, snapped onto
    an onset so the mix engine's fade-in rises out of a note, not a sustain."""
    frames = [f for f in analysis.get("frames") or [] if f["t"] <= total_s]
    lo, hi = 1.0, total_s - want_s - 1.0
    if not frames or hi <= lo:
        return 1.0
    peaks = flux_peaks(frames, total_s)
    times = [f["t"] for f in frames]
    levels, voiced = [0.0], [0]
    for f in frames:  # prefix sums keep a 1 h item cheap
        levels.append(levels[-1] + (f["m"] if f["m"] > -100 else 0.0))
        voiced.append(voiced[-1] + (1 if f["m"] > -100 else 0))
    peak_flags, running = [], 0
    peak_set = set(round(p, 3) for p in peaks)
    for f in frames:
        running += 1 if round(f["t"], 3) in peak_set else 0
        peak_flags.append(running)

    def window(start):
        i0 = bisect.bisect_left(times, start)
        i1 = bisect.bisect_left(times, start + want_s)
        count = voiced[i1] - voiced[i0]
        if count <= 0:
            return None
        level = (levels[i1] - levels[i0]) / count
        onsets = (peak_flags[max(0, i1 - 1)] - peak_flags[max(0, i0 - 1)]) / want_s
        return level, onsets

    candidates = []
    step = 1.0
    start = lo
    while start <= hi:
        got = window(start)
        if got:
            candidates.append((start, *got))
        start += step
    if not candidates:
        return round(lo, 2)
    med_level = _median([c[1] for c in candidates])
    med_onsets = _median([c[2] for c in candidates])
    scale = max(1.0, abs(med_onsets))
    best = min(
        candidates,
        key=lambda c: abs(c[1] - med_level) / 3.0 + abs(c[2] - med_onsets) / scale,
    )
    snapped = _snap(best[0], peaks)
    return round(min(max(snapped, lo), hi), 2)


def _snap(start, peaks):
    near = [p for p in peaks if abs(p - start) <= 1.5]
    if not near:
        return start
    return min(near, key=lambda p: abs(p - start))


def download(url, dest, *, referer=None, max_bytes=250 * 1024 * 1024):
    data = http_get(url, binary=True, timeout=90, referer=referer)
    if len(data) > max_bytes:
        raise RuntimeError(f"file larger than {max_bytes // 1024 // 1024} MB: {url}")
    dest.write_bytes(data)
    return len(data)


def ia_file_url(identifier):
    """One item can hold a 1 h, 145 MB file; pick the smallest mp3 (bed quality is fine)."""
    md = get_json(f"https://archive.org/metadata/{identifier}")
    files = [
        f for f in md.get("files") or []
        if str(f.get("format", "")).lower() in ("vbr mp3", "128kbps mp3", "mp3", "ogg vorbis")
        or str(f.get("name", "")).lower().endswith((".mp3", ".ogg", ".oga"))
    ]
    if not files:
        return ""
    order = {"mp3": 0, "ogg": 1}
    files.sort(
        key=lambda f: (
            order.get(str(f.get("name", "")).rsplit(".", 1)[-1].lower(), 9),
            int(f.get("size") or 0),
        )
    )
    return f"https://archive.org/download/{identifier}/{urllib.parse.quote(files[0]['name'])}"


def resolve_file_url(cand):
    if cand.get("source") == "ia" and not cand.get("file_url"):
        cand["file_url"] = ia_file_url(cand.get("ia_id") or cand["id"])
    return cand.get("file_url") or ""


def fetch(target, *, duration, stage_dir=None, today=None):
    """Verify at the origin, then download, gate, pick a section and stage the file."""
    stage = Path(stage_dir).expanduser() if stage_dir else default_stage()
    cand = resolve_candidate(target)
    if not cand.get("id"):
        return {"error": "unknown_candidate", "reason": f"{target} is not in the index and is not a URL"}
    # Refuse on what the aggregator already proves (Freesound ToS, reupload, NC/ND/SA)
    # before spending a request on the origin page, then refuse again on the origin's
    # own field - the origin wins, so a stale label can only tighten the verdict.
    cand.update(policy(cand, today=today))
    if cand["verdict"] not in OK_VERDICTS and cand["verdict_reason"] in FATAL_REASONS:
        return {
            "error": "license_denied",
            "id": cand["id"],
            "verdict": cand["verdict"],
            "reason": cand["verdict_reason"],
            "license_evidence": cand.get("license_evidence", ""),
        }
    origin = verify_at_origin(cand)
    cand["origin_verified"] = bool(origin.get("ok"))
    if not origin["ok"]:
        return {
            "error": "origin_verify_failed",
            "id": cand["id"],
            "source_url": cand.get("source_url"),
            "reason": origin["detail"],
        }
    cand.update({k: v for k, v in origin.items() if k != "ok"})
    cand["origin_verified"] = True
    cand.update(policy(cand, today=today))
    if cand["verdict"] not in OK_VERDICTS:
        return {
            "error": "license_denied",
            "id": cand["id"],
            "verdict": cand["verdict"],
            "reason": cand["verdict_reason"],
            "license_evidence": cand.get("license_evidence", ""),
        }
    file_url = resolve_file_url(cand)
    if not file_url:
        return {"error": "no_file_url", "id": cand["id"], "reason": "source exposed no downloadable audio file"}
    stage.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="music-search-"))
    try:
        raw = tmp / "track.bin"
        try:
            download(file_url, raw, referer=cand.get("source_url") if cand.get("source") == "ccmixter" else None)
        except Exception as exc:  # noqa: BLE001 - a dead file is a result, not a crash
            return {"error": "download_failed", "id": cand["id"], "reason": str(exc)}
        sha = hashlib.sha256(raw.read_bytes()).hexdigest()
        total, ext = probe(raw)
        if total < duration + START_FLOOR_S:
            return {
                "error": "track_too_short",
                "id": cand["id"],
                "reason": f"{total:.1f}s < {duration}s + {START_FLOOR_S:g}s (1 s lead + 1 s tail)",
            }
        analysis = analyze(raw)
        bad = gate(analysis)
        if bad:
            return {"error": "gate_failed", "id": cand["id"], "reason": bad}
        start = pick_start(analysis, total, duration)
        dest = stage / f"{cand['id']}.{ext}"
        shutil.move(str(raw), dest)
        record = {
            "id": cand["id"],
            "title": cand.get("title", ""),
            "creator": cand.get("creator", ""),
            "license": cand["license"],
            "license_version": cand.get("license_version", ""),
            "license_url": cand["license_url"],
            "source_url": cand.get("source_url", ""),
            "file_url": file_url,
            "retrieved_at": _now(),
            "attribution_required": cand["attribution_required"],
            "attribution_text": attribution_block(cand),  # recomputed: the aggregator's credit is stale
            "verdict": cand["verdict"],
            "verdict_reason": cand["verdict_reason"],
            "license_evidence": cand.get("license_evidence", ""),
            "content_id_risk": cand["content_id_risk"],
            "jurisdiction_note": cand["jurisdiction_note"],
            "recording_is_original_transfer": cand["recording_is_original_transfer"],
            "sha256": sha,
            "duration_s": round(total, 3),
            "start_s": start,
            "mood": cand.get("mood") or [],
            "bpm": cand.get("bpm") or 0,
            "staged_file": str(dest),
            "stage_dir": str(stage),
            "path_in_container": f"/music/{dest.name}",
        }
        sidecar = stage / f"{cand['id']}.json"
        sidecar.write_text(json.dumps(record, indent=2) + "\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "path_in_container": record["path_in_container"],
        "start_s": record["start_s"],
        "title": record["title"],
        "creator": record["creator"],
        "license": record["license"],
        "license_url": record["license_url"],
        "source_url": record["source_url"],
        "attribution": record["attribution_text"],
        "id": record["id"],
        "duration_s": record["duration_s"],
        "verdict": record["verdict"],
        "content_id_risk": record["content_id_risk"],
        "sha256": record["sha256"],
        "sidecar": str(sidecar),
    }


# ------------------------------------------------------------------------ misc


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ms_to_s(value):
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    return round(ms / 1000.0, 1) if ms > 0 else None


def _clock_to_s(value):
    parts = str(value or "").split(":")
    if not parts or not parts[-1].strip().isdigit():
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return float(total)


def _year(value):
    m = re.search(r"(1[89]\d\d|20\d\d)", str(value or ""))
    return int(m.group(1)) if m else None


def _remastered(text):
    return bool(re.search(r"remaster|restored|reissue|digitally remastered", str(text), re.I))


def _first(value):
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _em(meta, key):
    val = (meta.get(key) or {}).get("value")
    return str(val).strip() if val is not None else ""


def _strip_tags(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text or ""))).strip()


def _clean_url(url):
    """Commons imageinfo urls carry utm tracking params; keep the bare file url."""
    parts = urllib.parse.urlsplit(str(url))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def build_parser():
    parser = argparse.ArgumentParser(prog="music_search.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="find license-cleared candidates for a vibe")
    s.add_argument("--vibe", required=True, help='e.g. "calm ambient", "tech", "epic"')
    s.add_argument("--source", choices=SOURCES, help="one source only (default: all)")
    s.add_argument("--min-s", type=float, default=0, help="minimum duration in seconds")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--refresh", action="store_true", help="ignore the on-disk cache")

    f = sub.add_parser("fetch", help="verify, download, gate and stage one track")
    f.add_argument("target", help="candidate id from `search`, or a URL")
    f.add_argument("--duration", type=float, required=True, help="seconds needed (video length)")
    f.add_argument("--stage-dir", help="default: $XDG_CACHE_HOME/promo-video/music (mounted at /music)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "search":
        payload = search(
            args.vibe, source=args.source, min_s=args.min_s, limit=args.limit, refresh=args.refresh
        )
        print(json.dumps(payload, indent=2))
        return 0
    payload = fetch(args.target, duration=args.duration, stage_dir=args.stage_dir)
    print(json.dumps(payload, indent=2))
    return 1 if payload.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
