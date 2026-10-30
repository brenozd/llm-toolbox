---
name: music-search
description: "Find, license-gate and stage a music bed for promo-video (Openverse, Internet Archive, ccMixter). Use for: \"find music for this video\", \"soundtrack for the promo\", \"license of this track\", /music-search."
allowed-tools:
  - Bash
---

# music-search

Find, license-gate, verify, trim and stage a music bed for promo-video (stdlib python + the host's
ffmpeg/ffprobe). **Host-only: it needs network and promo-video's exec container has none.** Workflow:
`search` a vibe (candidates already filtered by verdict and indexed) → `fetch` one candidate id
(verify at the source record, download, ffprobe, gate, trim, stage) → JSON into `spec.music`.

```bash
S=skills/music-search/scripts/music_search.py
python3 $S search --vibe "calm ambient" [--source openverse|ia|ccmixter] [--min-s 30] [--limit 5] [--refresh]
python3 $S fetch <candidate-id> --duration 42 [--stage-dir DIR]
```

`fetch` takes only an id from a prior `search` (index in
`${XDG_CACHE_HOME:-~/.cache}/promo-video/candidates.json`): no URL entry point, since a bare file URL
carries no license. `--duration` is the video length; a longer track is trimmed from a fixed
`start_s` (3 s in, clamped to keep 1 s of head and 1 s of tail — shorter is refused) and only that
window is analysed. Stage defaults to `${XDG_CACHE_HOME:-~/.cache}/promo-video/music`, mounted
read-only at `/music` (no copy step). The plugin's mount pins `${HOME}/.cache/promo-video/music`, so
with `XDG_CACHE_HOME` set the file lands where `/music` cannot see it: `fetch` then prints a
`mount_hint` — restage with `--stage-dir "$HOME/.cache/promo-video/music"` (or move the mount), else
the spec lints `music_path_missing`. Internet Archive items can hold 145 MB files at ~1 MB/s while
every call has 60 s, so `fetch` reads the size from the item listing and refuses `download_too_large`
*before the first byte* when even the smallest audio file is over 40 MB, and `download_too_slow` when
a transfer misses its 45 s wall budget (no partial or ranged download: pick another candidate).
Openverse is anonymous and rate-limited (20/min; 10 s per attempt, `Retry-After` honoured up to
10 s), so successful results are cached a day (`--refresh` bypasses); a failure is not cached and
shows up in `sources` with its status (`openverse:error:HTTP429`). Vibe → tags (`VIBES`):
`ambient` ambient/drone · `calm` calm/chill/soft · `tech` electronic/synth · `epic`
epic/trailer/cinematic · `playful` upbeat/happy/fun · `elegant` piano/classical; ranking is tag
intersection, then the Content ID risk level as tie-break — audio features flip top-1.

## License policy (`verdict` is the only field `mix` may trust)

| Verdict | Licenses | Why |
| --- | --- | --- |
| allow | CC0 1.0, PDM, PD + original transfer before the cutoff | no attribution required; credit block still written |
| attribution | CC BY 3.0 / 4.0 only | commercial OK; credit, license link, changes note mandatory |
| deny | any BY-SA | sync-to-picture is Adapted Material → whole video would be BY-SA |
| deny | any NC / any ND | a promo is commercial; we trim, fade and sync (a modification) |
| deny | CC BY 2.5 / 2.0 / 1.0, or a BY with no version | jurisdictional ports, and no version means no terms — never assume 4.0 |
| deny | PD + third-party recording, unknown year, an uploader-only year, or not yet expired | separate phonogram right; US 95y rule, cutoff = current year − 95; the year must come from the item metadata (IA `/metadata`), not the uploader's `year` field |
| deny | Freesound-hosted files (`cdn.freesound.org`) | ToS forbid use outside their app — skip their Openverse previews |
| deny | reupload / mirror channels ("reupload", "ripped", "no copyright intended", "not mine") | the rights field of a copy proves nothing |
| deny | unknown/empty license | nothing to defend to a reviewer |

Rights are verified from the source's own structured record *before* download — Internet Archive
`/metadata`, the ccMixter API, the Openverse audio record — never from a scraped HTML page: the
literal string goes in `license_evidence` and a record that contradicts the aggregator or re-routes
the file to another host is refused.

## Output contract

`fetch` prints the `spec.music` fields on stdout — `path_in_container` (`/music/<id>.mp3`), `start_s`,
`title`, `creator`, `license`, `license_url`, `source_url`, `attribution`, `verdict`,
`content_id_risk`, `content_id_reasons`, `content_id_dispute`, `duration_s`, `sha256`, `sidecar`
(plus `mount_hint` when the stage is not the mounted directory); the sibling `<id>.json` carries the
full record. Set `spec.music = {"path": path_in_container, "start_s": …, <license fields>, "volume_db": -18, "duck": 12}`.
**Credits:** an `attribution` verdict must ship `attribution` verbatim — CC BY 4.0 §3(a) creator,
copyright notice, license name + URI, material URI, plus the `Changes:` line. Lint errors
`music_license_missing` (BY track, empty attribution) and `credits_missing` (credit not in CREDITS.txt).

## Notes

- **Content ID risk comes with its reasons.** `content_id_risk` (`low`/`medium`/`high`) ships
  `content_id_reasons` — `cc0_or_pdm_from_rights_holder`, `pd_era_disc_reissued_by_a_label` (labels
  reissue and re-claim PD-era discs), `cc_by_without_credit_is_an_easy_claim_target`,
  `cc0_or_pdm_via_an_aggregator_not_the_rights_holder` — and one `content_id_dispute` line in the
  sidecar: keep `<id>.json` (`license_evidence`, `source_url`, `sha256`) and answer the claim with it.
  `search` breaks a `vibe_score` tie by risk, so rights-holder CC0/PDM wins the tie. No claim-proof
  catalogue exists: this is paperwork, not prevention.
- Errors are results, not crashes: `unknown_candidate`, `license_denied`, `origin_verify_failed`,
  `track_too_short`, `download_too_large`, `download_too_slow`, `download_failed`, `analysis_failed`,
  `gate_failed` exit 1 with `{error, id, reason}` (+ `size_bytes`/`deadline_s` on a download). No
  candidate → "no results" + the payload `reason`; the mix stays silent.
- Gate rejects digital silence, LRA > 32 LU, noise-dominated (centroid > 4 kHz or rolloff > 12 kHz)
  and too-dark (centroid < 250 Hz with rolloff < 600 Hz) windows — not spectral flatness.
