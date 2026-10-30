---
name: music-search
description: "Find, license-gate and stage a music bed for promo-video (Openverse, Internet Archive, ccMixter, Commons). Use for: \"find music for this video\", \"soundtrack for the promo\", \"license of this track\", /music-search."
allowed-tools:
  - Bash
---

# music-search

Find, license-gate, verify, trim and stage a music bed for promo-video. Stdlib python plus the
host's ffmpeg/ffprobe. **Host-only: it needs network and promo-video's exec container has none.**

Workflow: `search` a vibe (candidates already filtered by verdict) → `fetch` one cleared candidate
(verify at origin, download, ffprobe, gate, pick window, stage) → JSON into `spec.music`, credit into `/work/CREDITS.txt`.

```bash
S=skills/music-search/scripts/music_search.py
python3 $S search --vibe "calm ambient" [--source openverse|ia|ccmixter|commons] [--min-s 30] [--limit 5] [--refresh]
python3 $S fetch <candidate-id|url> --duration 42 [--stage-dir DIR]
```

`--duration` is the video length; a longer track is trimmed from `start_s`. Default stage is
`${XDG_CACHE_HOME:-~/.cache}/promo-video/music`, mounted read-only at `/music` — no copy step. The
plugin's docker mount pins `${HOME}/.cache/promo-video/music`, so with `XDG_CACHE_HOME` set the file
lands where `/music` cannot see it (`music_path_missing`): either `--stage-dir "$HOME/.cache/promo-video/music"`
or point the mount at your `$XDG_CACHE_HOME`. Openverse
is anonymous and rate-limited (20/min), so results are cached a day (`--refresh` bypasses). Vibe → tag
sets (`VIBES`): `ambient` ambient/atmosphere/drone · `calm` calm/chill/soft/peaceful · `tech`
technology/electronic/synth · `epic` epic/trailer/cinematic/orchestral · `playful` upbeat/happy/fun ·
`elegant` piano/classical/minimal. Ranking is tag intersection only — audio features flip top-1.

## License policy (`verdict` is the only field `mix` may trust)

| Verdict | Licenses | Why |
| --- | --- | --- |
| allow | CC0 1.0, PDM, PD + original transfer before the cutoff | no attribution required; credit block still written |
| attribution | CC BY 3.0 / 4.0 only | commercial OK; credit, license link, changes note mandatory |
| deny | any BY-SA | sync-to-picture is Adapted Material → whole video would be BY-SA |
| deny | any NC / any ND | a promo is commercial; we trim, fade and sync (a modification) |
| deny | CC BY 2.5 / 2.0 / 1.0, or a BY with no version | jurisdictional ports, and no version means no terms — never assume 4.0 |
| deny | PD + third-party recording, unknown year, an uploader-only year, or not yet expired | separate phonogram right; US 95y rule, cutoff = current year − 95; the year must come from item metadata (IA `/metadata/`, Commons extmetadata), not the uploader's `year` field |
| deny | Freesound-hosted files (`cdn.freesound.org`) | ToS forbid use outside their app — skip their Openverse previews |
| deny | reupload / mirror channels ("reupload", "ripped", "no copyright intended", "not mine") | the rights field of a copy proves nothing |
| deny | unknown/empty license | nothing to defend to a reviewer |

Rights are verified at the origin (`foreign_landing_url`) *before* download; the literal rights string
stays in `license_evidence`, and the sidecar keeps `jurisdiction_note` (CC0/PDM scope, EU 70y term).
A web page licenses the file only through its own node — `<a rel="license">` or an element whose
class/id says license/credit/attribution/rights; a footer link or a stray `/by/` href elsewhere is
not evidence, and the credit block is rebuilt after verification, never reused from `search`.

## Output contract

`fetch` prints the `spec.music` fields on stdout:

```json
{"path_in_container":"/music/<id>.mp3","start_s":3.2,"title":"…","creator":"…","license":"CC BY 4.0",
 "license_url":"https://creativecommons.org/licenses/by/4.0/","source_url":"…","attribution":"…",
 "verdict":"attribution","content_id_risk":"medium","duration_s":180.4,"sha256":"…","sidecar":"…"}
```

Set `spec.music = {"path": path_in_container, "start_s": …, <license fields>, "volume_db": -18, "duck": 12}`.
The sibling `<id>.json` sidecar carries the full record (evidence, sha256, jurisdiction note).
**Credits:** an `attribution` verdict must ship `attribution` verbatim — CC BY 4.0 §3(a) creator,
copyright notice, license name + URI, material URI, plus the `Changes:` line the script adds. Lint
errors `music_license_missing` on a BY track with empty attribution; `verify` errors `credits_missing`
when the credit never reaches `CREDITS.txt`.

## Notes

- **Content ID risk is unmitigated.** CC0/PDM from archive.org / ccMixter / Commons is `low`, PD-era
  discs `high` (labels reissue and re-claim them), the rest `medium`. No allowlisted label, no
  Pixabay/Mixkit source: there is no claim-proof catalogue to point at — say so, don't imply safety.
- Errors are results, not crashes: `license_denied`, `origin_verify_failed`, `track_too_short`,
  `gate_failed`, `download_failed` exit 1 with `{error, id, reason}` — report the reason.
- No candidate → say "no results" plus the payload `reason`; the mix stays silent (no fallback).
- Gate rejects digital silence, LRA > 32 LU and noisy/period transfers (centroid > 4 kHz, rolloff
  > 12 kHz), not spectral flatness.
