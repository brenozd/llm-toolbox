#!/usr/bin/env python3
"""music-search: find, license-gate, verify, trim and stage a music bed for storyboard-video.

python3 stdlib only, plus the host's ffmpeg/ffprobe.

  music_search.py search --vibe "calm ambient" [--source openverse|ia|ccmixter]
                        [--min-s N] [--limit N] [--refresh]
  music_search.py fetch <candidate-id> --duration S [--stage-dir DIR]

The exec container mounts $HOME/.cache/storyboard-video/music read-only at /music, so there is no
copy step: `fetch` writes <stage>/<id>.<ext> + <stage>/<id>.json and prints the spec.music
JSON with path_in_container=/music/<file> (`mount_hint` when the stage is another directory).

`search` indexes every cleared candidate on disk; `fetch` takes only such an id and re-reads
the source's own structured record (archive.org /metadata, ccMixter query, Openverse audio
record) before it downloads a byte - a bare file URL carries no license, and an HTML landing
page is not structured evidence. Licenses: see `policy` and skills/music-search/SKILL.md."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")  # Openverse answers plain curl with 504s
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
SOURCES = ("openverse", "ia", "ccmixter")
OK_VERDICTS = ("allow", "attribution")
PD_RECORDING_YEARS = 95  # 17 U.S.C. 1401: first publication + 95y (1923-1946 ran the transition)
START_PAD_S = 2.0  # the window keeps 1 s of head and 1 s of tail: refuse anything shorter
START_OFFSET_S = 3.0  # fixed lead-in, past the encoder's own attack and any fade-in
MAX_LRA = 32.0  # LU; above this the track's texture moves too much to sit under a whole video
MAX_DOWNLOAD_BYTES = 40 << 20  # the caller has 60 s and IA serves ~1 MB/s: 40 MB is the ceiling
DOWNLOAD_DEADLINE_S = 45.0  # total wall budget for a download; probe+analyze+gate need the rest
READ_TIMEOUT_S = 90  # per-read socket timeout, clamped to what is left of the budget in download()
RISK_RANK = {"low": 0, "medium": 1, "high": 2}  # tie-break: provenance beats a claim magnet
CONTENT_ID_DISPUTE = (
    "Content ID claim? Keep <id>.json - license_evidence, source_url, sha256 are the whole "
    "counter-notice: dispute with that record, never re-upload or re-download around it.")
AUDIO_EXT = {"mp3": "mp3", "ogg": "ogg", "flac": "flac", "wav": "wav", "m4a": "m4a", "mp4": "m4a"}
# Licenses doc s7: a rights field on a reupload proves nothing; "mirror" is a track name, not a claim.
REUPLOAD_RE = re.compile(r"\bre-?upload|\bno copyright(?: infringement)? intended\b|\bnot mine\b"
                         r"|\bripped\b|\bpromoted upload\b|\bfull album upload\b", re.I)
# Vibe -> extra tags, the only stable ranker (audio features flip top-1: see the vibe report).
VIBES = {
    "ambient": ["ambient", "atmosphere", "atmospheric", "drone", "soundscape", "relaxing"],
    "calm": ["calm", "chill", "chillout", "soft", "mellow", "peaceful", "downtempo", "relaxing"],
    "tech": ["technology", "electronic", "synth", "synthesizer", "cyberpunk", "computer", "idm"],
    "epic": ["epic", "trailer", "cinematic", "orchestral", "dramatic", "powerful", "heroic"],
    "playful": ["playful", "upbeat", "happy", "fun", "quirky", "bouncy", "energetic"],
    "elegant": ["elegant", "piano", "classical", "minimal", "acoustic", "gentle"],
}
# License signatures, most specific first: a bare "licenses/by" prefixes by-sa/by-nc/by-nd, so scan
# the long forms first.
SIGNATURES = {
    "by-nc-nd": ("by-nc-nd", "byncnd", "by_nc_nd"),
    "by-nc-sa": ("by-nc-sa", "byncsa", "by_nc_sa"),
    "by-nc": ("by-nc", "bync", "by_nc"),
    "by-nd": ("by-nd", "bynd", "by_nd"),
    "by-sa": ("by-sa", "bysa", "by_sa"),
    "cc0": ("zero/1.0", "publicdomain/zero", "cc0", "cc-zero", "cc zero", "cczero"),
    "pdm": ("publicdomain/mark", "public-domain-mark", "public domain mark", "pdm",
            "licenses/publicdomain"),  # legacy CC PD dedication: a dedication about the file
    "by": ("licenses/by", "creativecommons.org/by", "/by/", "cc by", "cc-by"),
    "pd": ("public domain", "publicdomain", " pd "),
}
# Denials that no origin record can repair; anything else gets re-checked at the source.
FATAL_REASONS = {"freesound_preview_tos", "non_commercial_license", "no_derivatives_license",
                 "share_alike_sync", "pd_composition_third_party_recording", "reupload_or_mirror"}
LICENSE_NAME = {"by": "CC BY", "by-sa": "CC BY-SA", "by-nc": "CC BY-NC",
                "by-nd": "CC BY-ND", "by-nc-sa": "CC BY-NC-SA", "by-nc-nd": "CC BY-NC-ND"}
CANON_URL = {"cc0": "https://creativecommons.org/publicdomain/zero/1.0/",
             "pdm": "https://creativecommons.org/publicdomain/mark/1.0/"}

# ---- io

class HttpStatusError(RuntimeError):
    """A failed GET that remembers why: the status code, or the exception that killed it."""

    def __init__(self, url, tries, err):
        super().__init__(f"GET {url} failed after {tries} tries: {err}")
        self.status, self.kind = getattr(err, "code", None), type(err).__name__

def http_get(url, *, timeout=25, tries=3):
    """The single network door for JSON/text (tests replace this). One shot is not enough:
    api.openverse.org times out behind Cloudflare and archive.org's search backend returns
    transient 200s with an error body. A 429/503 is a wait, so its Retry-After wins over our
    own backoff (capped: one call has 60 s in total)."""
    err, headers = None, {"User-Agent": UA, "Accept": "*/*"}
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            err = exc
            if i + 1 < tries:
                asked = _retry_after(exc) if isinstance(exc, urllib.error.HTTPError) else None
                time.sleep(asked if asked is not None else 1.5 * (i + 1))
    raise HttpStatusError(url, tries, err)

def _retry_after(exc, cap=10.0):
    """-> seconds the origin asked us to wait, or None. Capped: one call has 60 s in total."""
    try:
        return min(max(float((exc.headers or {}).get("Retry-After")), 0.0), cap)
    except (AttributeError, TypeError, ValueError):
        return None

def get_json(url, *, tries=3, **kw):
    """archive.org answers 200 with {"error": "[BACKEND_ERROR] ..."} while Elasticsearch is
    busy; retry, and never let an error body look like an empty result set (it would then be
    cached as "no results" for a day)."""
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
    return Path(base) / "storyboard-video"

def default_stage():
    """`$XDG_CACHE_HOME/storyboard-video/music`; `fetch` prints a `mount_hint` when `/music` cannot
    see it: a silent miss costs a render, a hint costs one flag."""
    return cache_root() / "music"

def mounted_stage():
    """The host path `.claude-plugin/plugin.json` mounts read-only at /music (not XDG-driven)."""
    return Path.home() / ".cache" / "storyboard-video" / "music"

def cached(key, producer, *, refresh=False, ttl=86400):
    """On-disk cache: the Openverse anon quota is 20/min and 200/day."""
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
    return re.sub(r"-{2,}", "-", out).strip("-._")[:limit].strip("-._") or "x"

# ---- licenses

def parse_license(raw="", *, url="", version=""):
    """-> (license id, version). Aggregators hand out tokens ("cc0"), URLs (IA) and names
    ("CC0 (CC Zero)"), so scan all three."""
    text = " ".join(str(x) for x in (raw, url, version) if x).lower().replace("_", "-")
    token = str(raw or "").strip().lower()
    if token in ("cc0", "pdm", "pd", "by", "by-sa", "by-nd", "by-nc", "by-nc-sa", "by-nc-nd"):
        ver = str(version or "").strip()
        return token, ver if re.match(r"^\d\.\d$", ver) else _version_from(url, token)
    for name, needles in SIGNATURES.items():
        if any(n in text for n in needles):
            return name, _version_from(url or text, name, version)
    return "other", ""

def _version_from(text, lic, version=""):
    if lic in ("cc0", "pdm"):
        return str(version or "1.0") if lic == "pdm" else "1.0"
    if re.match(r"^\d\.\d$", str(version or "")):
        return str(version)
    m = re.search(r"/(\d\.\d)(?:/|$|\s)", str(text)) or re.search(r"\b(\d\.\d)\b", str(text))
    return m.group(1) if m else ""  # never invent a version: policy refuses an unknown one

def license_label(lic, version=""):
    if lic in LICENSE_NAME:
        return f"{LICENSE_NAME[lic]} {version}".strip()
    return {"cc0": "CC0 1.0", "pdm": "Public Domain Mark 1.0", "pd": "Public domain"}.get(lic, "OTHER")

def license_url_for(lic, version=""):
    if lic in CANON_URL:
        return CANON_URL[lic]
    if lic in LICENSE_NAME:
        return f"https://creativecommons.org/licenses/{lic}/{version + '/' if version else ''}"
    return ""

def pd_cutoff(today=None):
    """US recordings enter the PD 95 years after publication; the cutoff moves every 1 January."""
    return (today or date.today()).year - PD_RECORDING_YEARS

def policy(cand, *, today=None):
    """License -> verdict, always recomputed from the evidence: `verdict` is the only field
    `mix` may trust, so it is never copied from the source."""
    today = today or date.today()
    lic = cand.get("license_id") or "other"
    ver = str(cand.get("license_version") or "")
    ver = ver if re.match(r"^\d\.\d$", ver) else ""  # unparsable version == unknown, not a guess
    host = str(cand.get("host") or "").lower()
    year, cutoff = cand.get("published_year"), pd_cutoff(today)
    original = cand.get("original_transfer", True)
    out = {"license": license_label(lic, ver), "license_id": lic, "license_version": ver,
           "license_url": cand.get("license_url") or license_url_for(lic, ver),
           "attribution_required": lic in LICENSE_NAME,
           "recording_is_original_transfer": bool(original)}
    if cand.get("reupload"):
        # Licenses doc s7: a rights field on a reupload/mirror channel proves nothing.
        verdict, reason = "deny", "reupload_or_mirror"
        note = "Origin is a reupload/mirror channel, not the rights-holder: refuse."
    elif "freesound" in host or str(cand.get("provider") or "").lower() == "freesound":
        # Freesound ToS forbids use outside their app; Openverse audio is ~100% their previews.
        verdict, reason = "deny", "freesound_preview_tos"
        note = "Freesound ToS: API content may not be used outside their app."
    elif lic == "cc0":
        verdict, reason = "allow", "cc0_waives_copyright_and_neighbouring_rights"
        note = "CC0 1.0 waives copyright and related rights worldwide; no endorsement implied."
    elif lic == "pdm":
        verdict, reason = "allow", "public_domain_mark"
        note = "PDM is a label, not a license: the file is declared free of known restrictions."
    elif lic == "pd":
        note = (f"US: recordings first published before {cutoff} are PD (95y rule, computed "
                f"{today.year}); EU/UK: phonogram term 70y from publication. A remastered "
                f"reissue can carry a new phonogram right.")
        confirmed = cand.get("published_year_source") in ("metadata", "extmetadata")
        if not original:
            verdict, reason = "deny", "pd_composition_third_party_recording"
        elif year is None:
            verdict, reason = "deny", "pd_recording_year_unknown"
        elif not confirmed:  # an uploader's year is a claim; only the item metadata dates it
            verdict, reason = "deny", f"pd_recording_year_unconfirmed_{year}"
        elif int(year) >= cutoff:
            verdict, reason = "deny", f"pd_recording_not_expired_{year}_cutoff_{cutoff}"
        else:
            verdict, reason = "allow", f"pd_recording_published_{year}_before_{cutoff}"
    elif "nc" in lic:
        verdict, reason = "deny", "non_commercial_license"
        note = "A product promo is commercial; NC is not waivable by 'no ads'."
    elif "nd" in lic:
        verdict, reason = "deny", "no_derivatives_license"
        note = "Syncing and trimming is a modification; ND forbids it."
    elif "sa" in lic:
        verdict, reason = "deny", "share_alike_sync"
        note = "Sync-to-picture is Adapted Material, so the whole video would be BY-SA."
    elif lic in LICENSE_NAME and not ver:  # 3.0/4.0 terms only, and 4.0 is never assumed
        verdict, reason = "deny", "cc_by_version_unknown"
        note = "No CC BY version at the origin, so no version's terms: refuse."
    elif lic in LICENSE_NAME and float(ver) < 3.0:
        verdict, reason = "deny", f"cc_by_{ver}_unsupported"
        note = "CC BY 2.5 and older are jurisdictional ports, not the 3.0/4.0 terms: refuse."
    elif lic in LICENSE_NAME:
        verdict, reason = "attribution", f"cc_by_{ver}_needs_credit"
        note = "Commercial use OK; credit, license link and changes note are mandatory."
    else:
        verdict, reason = "deny", "license_unknown"
        note = "No usable license string at the origin: refuse."
    out.update(verdict=verdict, verdict_reason=reason, jurisdiction_note=note)
    out["content_id_risk"], out["content_id_reasons"] = content_id_assessment(cand, lic, year, cutoff)
    return out

def content_id_assessment(cand, lic, year, cutoff):
    """-> (level, reasons). A bare level cannot be argued with; the reasons are the brief."""
    if lic in ("cc0", "pdm") and cand.get("source") in ("ia", "ccmixter"):
        return "low", ["cc0_or_pdm_from_rights_holder"]
    if lic == "pd" or (year and int(year) < cutoff):
        # the remaster of a PD-era disc asserts a new phonogram right: the classic claim
        return "high", ["pd_era_disc_reissued_by_a_label"]
    if lic in LICENSE_NAME:
        return "medium", ["cc_by_without_credit_is_an_easy_claim_target"]
    return "medium", ["cc0_or_pdm_via_an_aggregator_not_the_rights_holder"]

def attribution_block(track, changes="trimmed and synced to video, no other edits"):
    """CC BY 4.0 s3(a)(1)(A)-(E): creator, copyright notice, license name+URI, material URI,
    changes note - one block covers all five."""
    lic = track.get("license") or license_label(track.get("license_id", "other"))
    url = track.get("license_url") or license_url_for(track.get("license_id", "other"))
    title, creator = track.get("title") or "Untitled", track.get("creator") or "Unknown creator"
    lines = [f'"{title}" by {creator} - {lic}']
    if track.get("copyright"):
        lines.append(f"Copyright: {track['copyright']}")
    lines += [f"Source: {track.get('source_url') or 'n/a'} - License: {url}",
              f"Changes: {changes}."]
    lines.append(track.get("disclaimer") or
                 "Provided as-is, without warranty of any kind; no endorsement by the creator is implied.")
    return " | ".join(lines)

# ---- search

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

CAND_DEFAULTS = {"id": "", "source": "", "provider": "", "host": "", "title": "", "creator": "",
                 "license_id": "other",  # a claim only: `policy` recomputes the verdict
                 "license_version": "", "license_url": "", "source_url": "", "file_url": "",
                 "duration_s": None, "mood": [], "published_year": None, "reupload": False,
                 # published_year_source: "metadata"/"extmetadata" = cross-checked, "uploader" = a claim
                 "published_year_source": "", "original_transfer": True}

def _cand(**kw):
    cand = dict(CAND_DEFAULTS, mood=[])
    cand.update(kw)
    return cand

def _reupload(*texts):
    """Licenses doc s7: a rights field on a reupload or mirror channel is not evidence."""
    return bool(REUPLOAD_RE.search(" ".join(str(t or "") for t in texts)))

def search_openverse(vibe, limit, *, refresh=False):
    # license=pdm returns 0 audio items on Openverse (live-check), so PDM rides in from IA.
    params = {"q": vibe, "license": "cc0,by", "page_size": str(min(20, max(limit * 4, 10)))}
    url = "https://api.openverse.org/v1/audio/?" + urllib.parse.urlencode(params)
    # 10 s a shot: 3 shots + backoff stay inside the caller's 60 s; the cache hides a slow read.
    data = cached(f"openverse-{vibe}-{limit}",
                  lambda: get_json(url, timeout=10), refresh=refresh)
    out = []
    for r in data.get("results") or []:
        file_url = r.get("url") or ""
        lic, ver = parse_license(r.get("license"), url=r.get("license_url"),
                                 version=r.get("license_version"))
        out.append(_cand(
            id="ov-" + slug(r.get("id") or file_url, 12), source="openverse",
            provider=r.get("source") or r.get("provider") or "",
            host=urllib.parse.urlsplit(file_url).netloc.lower(),
            title=(r.get("title") or "").strip(), creator=r.get("creator") or "",
            license_id=lic, license_version=ver,
            license_url=r.get("license_url") or license_url_for(lic, ver),
            source_url=r.get("foreign_landing_url") or r.get("detail_url") or "",
            file_url=file_url, duration_s=_ms_to_s(r.get("duration")),
            mood=sorted({str(t.get("name", "")).lower() for t in (r.get("tags") or []) if t.get("name")}),
            reupload=_reupload(r.get("title")), ov_id=r.get("id") or ""))  # re-read by fetch
    return out

def search_ia(vibe, limit, *, refresh=False):
    # licenseurl is uploader-set, so it is only a claim: fetch re-verifies at /metadata/.
    # A slash wildcard (`*licenses/by*`) makes archive.org's ES answer BACKEND_ERROR; `*by*` does not.
    words = " OR ".join(w for w in re.findall(r"[a-z0-9]+", vibe.lower()) if len(w) > 2) or vibe
    params = [("q", f"({words}) AND mediatype:audio AND "
                    "(licenseurl:*publicdomain* OR licenseurl:*by*)"),
              ("rows", str(min(50, max(limit * 3, 10)))), ("output", "json")]
    params += [("fl[]", f) for f in ("identifier", "title", "creator", "licenseurl", "subject", "year")]
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params)
    data = cached(f"ia-{words}-{limit}", lambda: get_json(url), refresh=refresh)
    out = []
    for d in ((data.get("response") or {}).get("docs")) or []:
        lic, ver = parse_license(d.get("licenseurl"))
        ident = d.get("identifier") or ""
        subject = d.get("subject") or []
        subject = re.split(r"[;,]", subject) if isinstance(subject, str) else subject
        year = _year(d.get("year") or d.get("date"))
        out.append(_cand(
            id="ia-" + slug(ident, 50), source="ia", provider="archive.org", host="archive.org",
            title=str(d.get("title") or ident), creator=_first(d.get("creator")),
            license_id=lic, license_version=ver, ia_id=ident, published_year=year,
            license_url=d.get("licenseurl") or license_url_for(lic, ver),
            source_url=f"https://archive.org/details/{ident}",
            file_url="",  # resolved per item in fetch: a 1 h item can hold 145 MB files
            # archive.org's `year`/`date` is the uploader's own field: fetch re-reads the item metadata.
            published_year_source="uploader" if year else "",
            reupload=_reupload(d.get("title"), " ".join(str(s) for s in subject)),
            original_transfer=not _remastered(" ".join(str(x) for x in (d.get("title"), subject))),
            mood=sorted({str(s).strip().lower() for s in subject if str(s).strip()})))
    return out

def search_ccmixter(vibe, limit, *, refresh=False):
    out = []
    for code in ("zero", "by"):
        params = {"datasource": "uploads", "lic": code, "search": vibe, "f": "json",
                  "limit": str(limit)}
        url = "https://ccmixter.org/api/query?" + urllib.parse.urlencode(params)
        data = cached(f"ccmixter-{code}-{vibe}", lambda: get_json(url), refresh=refresh)
        if isinstance(data, dict):
            data = data.get("records") or data.get("results") or []
        out += [_ccm_cand(item) for item in data]
    return out

def _ccm_cand(item):
    audio = [f for f in item.get("files") or []
             if str((f.get("file_format_info") or {}).get("media-type", "")).startswith("audio")]
    best = sorted(audio, key=lambda f: (str(f.get("file_nicname")) != "mp3",
                                        int(f.get("file_rawsize") or 0)))[:1]
    lic, ver = parse_license(item.get("license_name"), url=item.get("license_url"))
    fmt = (best[0].get("file_format_info") or {}) if best else {}
    return _cand(
        id="ccm-" + slug(item.get("upload_id")), source="ccmixter", provider="ccmixter.org",
        host="ccmixter.org", title=item.get("upload_name") or "",
        creator=item.get("user_real_name") or item.get("user_name") or "",
        license_id=lic, license_version=ver, ccm_id=item.get("upload_id"),
        license_url=item.get("license_url") or license_url_for(lic, ver),
        source_url=item.get("file_page_url") or "",
        file_url=(best[0].get("download_url") or "") if best else "", duration_s=_clock_to_s(fmt.get("ps")),
        bpm=(item.get("upload_extra") or {}).get("bpm") or 0,
        mood=sorted({t.strip().lower() for t in str(item.get("upload_tags") or "").split(",") if t.strip()}),
        reupload=_reupload(item.get("upload_name"), item.get("upload_tags")))

SEARCHERS = {"openverse": search_openverse, "ia": search_ia, "ccmixter": search_ccmixter}

def search(vibe, *, source=None, min_s=0, limit=5, refresh=False, today=None):
    """Rank candidates by tag overlap, then drop what the policy denies. No fallback track: an
    empty pool is a valid answer and the mix stays silent."""
    tags = vibe_tags(vibe)
    notes, raw = [], []
    for name in ([source] if source else SOURCES):
        try:
            got = SEARCHERS[name](vibe, limit, refresh=refresh)
            notes.append(f"{name}:{len(got)}")
            raw += got
        except Exception as exc:  # noqa: BLE001 - a dead source is not a dead search
            # "HTTP429" (wait) and "connection reset" (dead) are not the same story
            status = getattr(exc, "status", None)
            why = f"HTTP{status}" if status else getattr(exc, "kind", type(exc).__name__)
            notes.append(f"{name}:error:{why}")
    kept, skipped = [], {}
    for cand in raw:
        cand.update(policy(cand, today=today))
        if cand["verdict"] not in OK_VERDICTS:
            why = cand["verdict_reason"].split("_cutoff")[0]
            skipped[why] = skipped.get(why, 0) + 1
            continue
        if min_s and cand.get("duration_s") and cand["duration_s"] < min_s:
            skipped["too_short"] = skipped.get("too_short", 0) + 1
            continue
        cand["attribution"] = attribution_block(cand)
        cand["vibe_score"] = vibe_score(cand, tags)
        cand["bpm"] = cand.get("bpm") or 0
        kept.append(cand)
    seen, unique = set(), []
    # Vibe first, then provenance: at equal overlap CC0/PDM from the rights holder beats CC BY.
    for cand in sorted(kept, key=lambda c: (-c["vibe_score"], RISK_RANK.get(c["content_id_risk"], 9),
                                            c["source"], c["title"].lower())):
        key = (cand["title"].lower(), cand["creator"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(cand)
    results = unique[:limit]
    remember(results)
    payload = {"vibe": vibe, "tags": sorted(tags), "count": len(results), "results": results,
               "sources": notes, "skipped": skipped}
    if not results:
        why = ", ".join(f"{k}x{v}" for k, v in sorted(skipped.items())) or "no candidates"
        payload["reason"] = (
            f"no allow/attribution track for {vibe!r} ({'; '.join(notes)}; skipped {why}) - "
            "keep the mix silent: there is no fallback track.")
    return payload

# ---- candidate index

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
    """`fetch` takes a candidate id from a prior `search`: only the index knows what the aggregator
    claimed, which source record to re-read and which file to pull."""
    return dict(load_index().get(str(target).strip()) or {})

# ---- verify at the origin

def verify_at_origin(cand):
    """Re-read the source's own structured record and quote its rights field, before any
    download: an aggregator's license field can be stale, wrong, or missing."""
    source = cand.get("source")
    try:
        if source == "ia":
            if not cand.get("ia_id"):
                return {"ok": False, "detail": "no archive.org identifier to re-read"}
            meta = get_json(f"https://archive.org/metadata/{cand['ia_id']}").get("metadata") or {}
            raw = meta.get("licenseurl") or meta.get("license") or ""
            lic, ver = parse_license(raw)
            out = _verified(raw, lic, ver, raw, f'archive.org metadata licenseurl="{raw}"', cand)
            # Cross-check the year: uploader `year` vs item metadata - disagree, and we refuse.
            year = _year(meta.get("date") or meta.get("year") or meta.get("publicdate"))
            if out.get("ok") and year and cand.get("published_year") and int(cand["published_year"]) != year:
                return {"ok": False, "detail": f"year conflict: search said {cand['published_year']}, metadata says {year}"}
            if out.get("ok") and year:
                out.update(published_year=year, published_year_source="metadata")
            return out
        if source == "ccmixter":
            params = urllib.parse.urlencode({"datasource": "uploads", "ids": cand.get("ccm_id"),
                                             "f": "json"})
            data = get_json(f"https://ccmixter.org/api/query?{params}")
            item = (data[0] if isinstance(data, list) and data else data) or {}
            raw = item.get("license_url") or item.get("license_name") or ""
            lic, ver = parse_license(item.get("license_name"), url=item.get("license_url"))
            return _verified(raw, lic, ver, item.get("license_url") or "",
                             f'ccmixter api license_url="{raw}"', cand)
        if source == "openverse":
            if not cand.get("ov_id"):
                return {"ok": False, "detail": "no openverse record id to re-read"}
            rec = get_json("https://api.openverse.org/v1/audio/"
                           f"{urllib.parse.quote(str(cand['ov_id']))}/")
            lic, ver = parse_license(rec.get("license"), url=rec.get("license_url"),
                                     version=rec.get("license_version"))
            return _verified(
                rec.get("license") or "", lic, ver, rec.get("license_url") or "",
                f'openverse record {cand["ov_id"]} license="{rec.get("license")}" '
                f'license_version="{rec.get("license_version")}"', cand,
                extra={  # the record can re-route the file, so host/provider re-enter `policy`
                    "host": urllib.parse.urlsplit(str(rec.get("url") or "")).netloc.lower(),
                    "provider": rec.get("source") or rec.get("provider") or "",
                    "file_url": rec.get("url") or "",
                    "source_url": rec.get("foreign_landing_url") or ""})
        return {"ok": False, "detail": f"no origin check available for source={source!r}"}
    except Exception as exc:  # noqa: BLE001 - unreachable origin == unverified
        return {"ok": False, "detail": f"origin unreachable: {type(exc).__name__}: {exc}"}

def _verified(raw, lic, ver, url, evidence, cand, *, extra=None):
    if not lic or lic == "other":
        return {"ok": False, "detail": f"origin record shows no usable license ({evidence})"}
    claimed = cand.get("license_id")
    if claimed and claimed not in ("other", lic):
        return {"ok": False, "detail": f"license mismatch: aggregator said {claimed}, "
                                       f"origin says {lic} ({evidence})"}
    out = {"ok": True, "license_id": lic, "license_version": ver or cand.get("license_version") or "",
           "license_url": url or cand.get("license_url") or license_url_for(lic, ver),
           "license_evidence": evidence, "raw_license": str(raw)}
    out.update({k: v for k, v in (extra or {}).items() if v})
    return out

# ---- audio

def probe(path):
    """-> (duration_s, container ext) from one ffprobe call."""
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration,format_name",
                          "-of", "default=nw=1", str(path)],
                         capture_output=True, text=True, timeout=180)
    data = dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)
    try:
        duration = float(data.get("duration") or 0)
    except ValueError:
        duration = 0.0
    names = str(data.get("format_name") or "").split(",")
    return duration, next((AUDIO_EXT[n] for n in names if n in AUDIO_EXT), "mp3")

def analyze(path, *, start=0.0, duration=None):
    """One ffmpeg pass over the picked window only -> loudness + spectral centroid/rolloff.
    Only that window reaches the mix, so only it is worth gating (a 1 h item stays cheap)."""
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-ss", f"{max(0.0, start):.3f}"]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", str(path), "-af",
            "aresample=48000,ebur128=metadata=1:peak=none,"
            "aspectralstats=measure=centroid+rolloff,ametadata=mode=print:file=-",
            "-f", "null", "-"]
    return parse_analysis(subprocess.run(cmd, capture_output=True, text=True, timeout=1800).stdout)

def parse_analysis(text):
    """ffmpeg's ametadata dump -> {"lufs", "lra", "frames": [{centroid, rolloff}, ...]}."""
    frames, cur = [], None
    for line in str(text).splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            cur = {"centroid": 0.0, "rolloff": 0.0}
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
        if key.startswith("lavfi.r128") and leaf in ("I", "LRA"):
            cur["lufs" if leaf == "I" else "lra"] = num
        elif "aspectralstats" in key and leaf in ("centroid", "rolloff"):
            cur[leaf] = num
    lufs = frames[-1]["lufs"] if frames and "lufs" in frames[-1] else -120.0
    return {"lufs": lufs, "lra": max((f.get("lra", 0.0) for f in frames), default=0.0),
            "frames": frames}

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
    # Hiss/cicadas put rolloff near Nyquist; a 78rpm transfer without cleanup sits low with no energy.
    if rolloff > 12000.0 or centroid > 4000.0:
        return "noise_dominated"
    if centroid < 250.0 and rolloff < 600.0:
        return "too_dark_rumble"
    return None

def pick_start(total_s, want_s):
    """Fixed lead-in, clamped so the window keeps 1 s of head and 1 s of tail: a plain offset
    beats scoring every window of a 1 h item, and 3 s still lands on musical material."""
    return round(min(START_OFFSET_S, max(1.0, total_s - want_s - 1.0)), 2)

# ---- fetch

_monotonic = time.monotonic  # one seam for the download deadline (tests replace it)

class DownloadError(RuntimeError):
    """A download that must surface as a result payload, not a traceback."""

    def __init__(self, code, reason, **detail):
        super().__init__(reason)
        self.code, self.detail = code, detail

def http_stream(url, *, timeout=READ_TIMEOUT_S, referer=None, chunk=1 << 20):
    """Single network door for downloads: yield the body in chunks, never buffer it all."""
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            block = resp.read(chunk)
            if not block:
                return
            yield block

def download(url, dest, *, referer=None, max_bytes=250 * 1024 * 1024,
             deadline_s=DOWNLOAD_DEADLINE_S):
    """Stream to disk, hashing as we go: a 145 MB archive file never sits in memory.
    deadline_s is a *total* wall budget, not a per-read socket timeout: at IA's ~1 MB/s the
    caller's 60 s Bash timeout would kill a slow file mid-flight, so it fails as a result.
    The socket timeout is clamped to the budget too: a bare READ_TIMEOUT_S read could otherwise
    block past the caller's 60 s on its own (the loop re-checks the budget after every block)."""
    digest, size, started = hashlib.sha256(), 0, _monotonic()
    with Path(dest).open("wb") as fh:
        for block in http_stream(url, referer=referer,
                                 timeout=max(1.0, min(READ_TIMEOUT_S, deadline_s))):
            size += len(block)
            if size > max_bytes:
                raise DownloadError("download_too_large", f"stream passed {max_bytes >> 20} MB: {url}",
                                    bytes_downloaded=size, limit_bytes=max_bytes)
            if _monotonic() - started > deadline_s:
                raise DownloadError("download_too_slow",
                                    f"fewer than {size >> 10} KB in {deadline_s:g} s: {url}",
                                    bytes_downloaded=size, deadline_s=deadline_s)
            digest.update(block)
            fh.write(block)
    return size, digest.hexdigest()

def ia_file(identifier):
    """-> (url, size_bytes, other_formats). One item can hold a 1 h, 145 MB file, so the smallest
    mp3 wins and its size comes from the same listing: `fetch` refuses an oversized file before
    the first byte, not 40 s into the stream."""
    files = [f for f in (get_json(f"https://archive.org/metadata/{identifier}").get("files") or [])
             if str(f.get("format", "")).lower() in ("vbr mp3", "128kbps mp3", "mp3", "ogg vorbis")
             or str(f.get("name", "")).lower().endswith((".mp3", ".ogg", ".oga"))]
    if not files:
        return "", 0, []
    order = {"mp3": 0, "ogg": 1}
    files.sort(key=lambda f: (order.get(str(f.get("name", "")).rsplit(".", 1)[-1].lower(), 9),
                              int(f.get("size") or 0)))
    pick = files[0]
    url = f"https://archive.org/download/{identifier}/{urllib.parse.quote(pick['name'])}"
    others = [f"{f['name']} ({int(f.get('size') or 0) >> 20} MB)" for f in files[1:4]]
    return url, int(pick.get("size") or 0), others
def resolve_file_url(cand):
    """-> (url, size_bytes, other_formats); size 0 means the source record listed no size."""
    if cand.get("source") == "ia" and not cand.get("file_url"):
        return ia_file(cand.get("ia_id") or "")
    return cand.get("file_url") or "", 0, []

def _denied(cand):
    return {"error": "license_denied", "id": cand["id"], "verdict": cand["verdict"],
            "reason": cand["verdict_reason"], "license_evidence": cand.get("license_evidence", "")}

def fetch(target, *, duration, stage_dir=None, today=None):
    """Verify at the source record, then download, probe, gate the picked window and stage."""
    stage = Path(stage_dir).expanduser() if stage_dir else default_stage()
    cand = resolve_candidate(target)
    if not cand.get("id"):
        return {"error": "unknown_candidate",
                "reason": f"{target} is not in the candidate index: run `search`, then use its id"}
    # Refuse on what the aggregator proves (Freesound/NC/ND/SA/reupload), then on the origin record.
    cand.update(policy(cand, today=today))
    if cand["verdict"] not in OK_VERDICTS and cand["verdict_reason"] in FATAL_REASONS:
        return _denied(cand)
    origin = verify_at_origin(cand)
    if not origin["ok"]:
        return {"error": "origin_verify_failed", "id": cand["id"],
                "source_url": cand.get("source_url"), "reason": origin["detail"]}
    cand.update({k: v for k, v in origin.items() if k != "ok"})
    cand["origin_verified"] = True
    cand.update(policy(cand, today=today))
    if cand["verdict"] not in OK_VERDICTS:
        return _denied(cand)
    file_url, size_bytes, other_formats = resolve_file_url(cand)
    if not file_url:
        return {"error": "no_file_url", "id": cand["id"],
                "reason": "source exposed no downloadable audio file"}
    if size_bytes > MAX_DOWNLOAD_BYTES:  # before the first byte: 40 MB already costs 60 s
        return {"error": "download_too_large", "id": cand["id"], "size_bytes": size_bytes,
                "limit_bytes": MAX_DOWNLOAD_BYTES,
                "reason": f"smallest audio file is {size_bytes >> 20} MB (cap "
                          f"{MAX_DOWNLOAD_BYTES >> 20} MB for a 60 s call); other audio files on "
                          f"the item: {'; '.join(other_formats) or 'none'}"}
    stage.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="music-search-"))
    try:
        raw = tmp / "track.bin"
        try:
            _, sha = download(file_url, raw, deadline_s=DOWNLOAD_DEADLINE_S,
                              referer=cand.get("source_url") if cand.get("source") == "ccmixter" else None)
        except DownloadError as exc:  # the cap and the wall clock are results, not crashes
            return {"id": cand["id"], **exc.detail, "error": exc.code, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - a dead file is a result, not a crash
            return {"error": "download_failed", "id": cand["id"], "reason": str(exc)}
        try:  # ffprobe/ffmpeg trouble is a result too, never a traceback
            total, ext = probe(raw)
            if total < duration + START_PAD_S:
                return {"error": "track_too_short", "id": cand["id"],
                        "reason": f"{total:.1f}s < {duration:g}s + {START_PAD_S:g}s (1 s head + 1 s tail)"}
            start = pick_start(total, duration)
            analysis = analyze(raw, start=start, duration=duration)  # the picked window only
        except Exception as exc:  # noqa: BLE001
            return {"error": "analysis_failed", "id": cand["id"],
                    "reason": f"{type(exc).__name__}: {exc}"}
        bad = gate(analysis)
        if bad:
            return {"error": "gate_failed", "id": cand["id"], "reason": bad}
        dest, sidecar = stage / f"{cand['id']}.{ext}", stage / f"{cand['id']}.json"
        shutil.move(str(raw), dest)
        record = {
            "id": cand["id"], "title": cand.get("title", ""), "creator": cand.get("creator", ""),
            "license": cand["license"], "license_version": cand.get("license_version", ""),
            "license_url": cand["license_url"], "source_url": cand.get("source_url", ""),
            "file_url": file_url, "retrieved_at": _now(), "sha256": sha,
            "attribution_required": cand["attribution_required"],
            "attribution_text": attribution_block(cand),  # rebuilt: the aggregator's credit is stale
            "verdict": cand["verdict"], "verdict_reason": cand["verdict_reason"],
            "license_evidence": cand.get("license_evidence", ""), "start_s": start,
            "content_id_risk": cand["content_id_risk"], "jurisdiction_note": cand["jurisdiction_note"],
            "content_id_reasons": cand.get("content_id_reasons") or [],
            "content_id_dispute": CONTENT_ID_DISPUTE,
            "recording_is_original_transfer": cand["recording_is_original_transfer"],
            "duration_s": round(total, 3), "mood": cand.get("mood") or [],
            "bpm": cand.get("bpm") or 0, "staged_file": str(dest), "stage_dir": str(stage),
            "path_in_container": f"/music/{dest.name}"}
        sidecar.write_text(json.dumps(record, indent=2) + "\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    payload = {k: record[k] for k in (
        "path_in_container", "start_s", "title", "creator", "license", "license_url",
        "source_url", "id", "duration_s", "verdict", "content_id_risk", "content_id_reasons",
        "sha256")}
    payload["attribution"] = record["attribution_text"]
    payload["content_id_dispute"] = CONTENT_ID_DISPUTE
    payload["sidecar"] = str(sidecar)
    if stage.resolve() != mounted_stage().resolve():
        payload["mount_hint"] = (
            f"staged in {stage}, but /music only sees {mounted_stage()} - pass "
            f'--stage-dir "{mounted_stage()}" or the render fails with music_path_missing')
    return payload

# ---- misc

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
    f.add_argument("target", help="candidate id from a prior `search`")
    f.add_argument("--duration", type=float, required=True, help="seconds needed (video length)")
    f.add_argument("--stage-dir", help="default: $XDG_CACHE_HOME/storyboard-video/music (mounted at /music)")
    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "search":
        payload = search(args.vibe, source=args.source, min_s=args.min_s,
                         limit=args.limit, refresh=args.refresh)
    else:
        payload = fetch(args.target, duration=args.duration, stage_dir=args.stage_dir)
    print(json.dumps(payload, indent=2))
    return 1 if payload.get("error") else 0

if __name__ == "__main__":
    sys.exit(main())
