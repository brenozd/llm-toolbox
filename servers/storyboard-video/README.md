# storyboard-video MCP

Builds a captioned promo video (MP4 + SRT + poster) from a repo, with every claim tied to a capture or `file:line`, plus an offline voice-over.
Works for web, CLI and GUI projects. Pair it with [`skills/storyboard-video`](../../skills/storyboard-video/). An `image` scene also accepts `video` (mp4/webm/gif, e.g. recorded by [`skills/screencapture`](../../skills/screencapture/)) in place of a still.

## Tools
`preflight`, `scan_repo`, `brand_tokens`, `extract_code`, `capture_web`, `capture_terminal`*, `capture_terminal_session`*, `capture_gui`*, `validate_spec`, `suggest_voices`, `narrate`, `animatic`, `shot_list`, `stills`, `audit_layout`, `reframe`, `cutdown`, `render` + `render_status`, `verify`, `deliver`, `round_log`.
(*) run repo code: only enabled when the container has `STORYBOARD_ALLOW_EXEC=1`, which the operator sets (plugin entry `storyboard-video-exec`), not the model.

## 16:9 and 9:16
Every capture tool takes `aspect` (`16:9` default, or `9:16`) and fills in that format's geometry, because the format is baked into the pixels: a landscape screenshot letterboxes in a portrait frame.

| aspect | web viewport | session cols x rows | gui screen | terminal cols |
|--------|--------------|---------------------|------------|---------------|
| `16:9` | 1440x810 (dsf 1) | 80x16 | 1280x720 | 100 |
| `9:16` | 540x960 (dsf 2) | 44x28 | 720x1280 | 40 |

The session grid's aspect is picked to match the content box (16:9 window 1444x633 in a 1587x755 box), so a recording fills the frame width instead of sitting in the middle as a small stamp.

Portrait keeps the top 10% / bottom 20% / sides 5% clear (the bands a phone UI covers): the content box is padded past both bands and the caption sits just above the bottom one. `reframe(spec_hash, aspect)` clones a spec into the other aspect, applies the portrait rules (max 4 bullets, terminal lines trimmed to ~40 cols, every lossy edit reported) and lists the captures whose geometry no longer matches, with the call that redoes them.

Images cover the frame and centre `scene.focus` instead of letterboxing: `layout.zoom_plan` clamps the pan to what the capture can cover and the zoom so the focus stays in shot. `stills` and `audit_layout` measure every text box of every scene (`getBoundingClientRect`) and warn when a box leaves the frame, sits in a safe zone, or is clipped inside its own box. `stills(spec_hash, at_s=N)` shoots that second of every scene instead of the review frame, and every still carries a `digest` (identical frame ⇒ identical digest), so two `at_s` runs of one scene prove the card stopped moving.

## Real terminal sessions
`capture_terminal_session` records a genuine session: Xvfb → xterm (no scrollbar) → `bash`, with every keystroke sent by `xdotool` and the screen grabbed by ffmpeg `x11grab`.
**The typing speed is staged** (`delay_ms` + seeded jitter); **the output is real** — the shell really runs the command and the MP4 is a recording of it, not an animation.
`steps` = `[{type:'type',text}|{type:'key',key}|{type:'wait_for',text,timeout_s}|{type:'hold_s',s}]`; `wait_for` polls the pty log and a timeout fails the take (no half clip). The MP4, a poster PNG and `session.json` (steps, seed, output text) land in `/work/captures/<id>/`. A `terminal` scene plays it inside a fake window title bar.
Size the window to the run — `rows = printed lines + 1` (the 16-row default leaves ~44 % of the frame blank at 9 lines, and the text then reads small because it is scaled down) — or pass **`crop_empty=true`** (opt-in on both terminal captures): the session take is re-encoded down to the rows that carry text, `capture_terminal` drops the trailing blank lines from its line list. It is off by default because the re-encode costs a second and changes the capture's size.
The image also ships **gcc + libc6-dev**, so a CLI demo can compile its own sample program inside the exec container and show the real compile (`gcc -O0 -o leak leak.c`) instead of shipping a binary.

## Voice-over (offline)
The image bundles no music. A track is found, licence-checked and staged by the [`skills/music-search`](../../skills/music-search/) skill into `${XDG_CACHE_HOME:-~/.cache}/storyboard-video/music`, which both plugin entries mount read-only at `/music` (the `XDG_CACHE_HOME` trap is in **Two plugin entries**); `spec.music = {"path": "/music/<id>.mp3", "start_s", "license", "volume_db", "duck"}` is linted against it (`music_path_missing`, `music_license_missing`, `music_license_incompatible`) and mixed by the render (see **Mix and loudness**). No track is not an error: a silent video is the default.

`narrate(spec_hash)` synthesizes every `scene.narration` with Pocket TTS (Kyutai, MIT; a CPU-only Rust binary, `pt-BR` and `en`) into one WAV per scene under `/work/audio/<spec_hash>/`, plus a `manifest.json` with the durations measured from the files. The binary (sha256-checked per arch) and the weights of both languages and of every catalogue voice are baked into the image at build time (`HF_HOME=/opt/hf`, `HF_HUB_OFFLINE=1`): no network, no torch, no Python in the engine; x86_64 needs AVX2. Cache key = `text + voice + lang + binary identity (name:size)` and `resolved_hash` also carries `RENDER_VERSION`, so a re-baked engine or a template change invalidates the cached WAVs/stills.
A scene then lasts `max(duration_s, audio + 0.4 s)`, and `spec.timeline()` reads the manifest — so the *resolved* hash (`spec_hash` + audio digest) changes when the speech changes, and old stills/renders are never reused (delivery is refused until you re-run `stills`).
`spec.lang` (`pt-BR`|`en`) is required as soon as a scene has narration; `spec.voice` overrides the default (`rafael` / `george`) and must be a catalogue voice (`bad_voice`); there is **no `speed`** (`speed_unsupported`): the voice sets pace and expressiveness. `suggest_voices(lang, pitch, emotion, pace, flow)` ranks the `en` catalogue (`voices.py`, 19 voices) from measured pace/pause/intonation; `pt-BR` offers only `rafael`; CC BY voices need the attribution in `NOTICE`; `jean`/`cosette` (CC BY-NC) are left out. `spec.say = {"LD_PRELOAD": "el di preload"}` is applied to the text *before* synthesis: `lint` warns (`say_missing`) for every acronym, snake_case/camelCase token or on-screen identifier a scene speaks without a mapping, and for speech faster than ~3.2 words/s (`narration_pace`). Transcribe the delivered MP4 with the `faster-whisper` MCP (`transcribe(audio_path=<the MP4>, language=spec.lang)`) and hold the round trip to a WER of **~0.15** on accent-stripped tokens; judge it with `small` (the default, `WHISPER_MODEL=small`) — `tiny` misreads enough to score a good line at 0.40. Spoken numbers need `scene.evidence` like any other claim (and the lint's blind spot is in **Limits**: it only fires on a number with a unit).

## Rough cut (animatic)
Hear the rhythm before capturing anything: round 3 judges structure, not pixels.
`narrate(spec_hash, scratch=true)` is the animatic pass — same engine, same cache, the same WAVs; the manifest only gains `"scratch": true` and the delivery `resolved_hash` does not move (the label is metadata, not a cache key).
`animatic(spec_hash)` is the **same render path** with `quality="animatic"`: 640x360 (360x640 in 9:16), 15 fps, hard cuts, a printed `ANIMATIC` watermark and no music. Every scene becomes a `bullets` card whose text is the AV script's visual column as a placeholder (`[captura: sessão de terminal: mint — 4.0s]`, in `spec.lang`) plus the spoken line, and it carries **no image/video/capture_id at all** — a rough cut never needs a capture and never shows a stale one. It runs as a background job like `render` (returns `job_id`, poll `render_status`; a 3-minute script takes over a minute), and the receipt points at `/work/animatic/<animatic hash>_ANIMATIC.mp4` (+ a `.json` receipt) **outside** `out/<resolved_hash>/`, with a hash salted by `stage="animatic"` (`spec.resolved_hash(spec, stage=...)`), so an animatic cannot be mistaken for the delivery. The return carries `pace_map`: per scene `{id, type, dur_s, words, wps, lead_s, tail_s, voice_s}`, measured from the manifest WAVs — `tail_s` is the time the picture holds after the line, `lead_s` the silence at the head of the card (today ~0: `timeline()` always stretches a scene to its audio, and a silent scene reports `tail_s = dur_s`). Its `caveat` is part of the answer: **a synth is more regular than a human**, so judge structure here and recompute with the final voice before locking a cut.
`shot_list(spec_hash)` turns the approved AV script into the captures to shoot, scene by scene and in playback order: `at_s`, `dur_s`, `voice_s`, `hold_s` (what the shot has on screen after its line ends), `silent_s` (lead + tail), `need`, the suggested `tool` (`capture_terminal_session` / `capture_web` / `extract_code`, with `call` args for a `file:line` evidence), `have` for a scene already captured, and the `file:line` `evidence` the shot has to prove. Its only `warnings` are **warn-only** (`shot_no_hold`: the voice leaves under a second). No new spec lint: `short_hold` / `hold_too_long` already cover the same ground, and a rough cut must never block `validate_spec`.

## Mix and loudness
The render builds one soundtrack per video (`storyboard_video_mcp/audio.py`), then muxes it: the picture is
copied untouched, the audio becomes **AAC 192 kbit/s** 48 kHz stereo, exactly as long as the picture.

| layer | what it does |
|---|---|
| music bed (`spec.music`) | the staged track (from `start_s`, looped if the video outlasts it) is trimmed to the video length, faded in 1.5 s and out 2.5 s (both clamped to a quarter of a short video), then set to `volume_db` (default -18 dB) |
| narration | each scene's WAV laid at its scene offset (`narration_track`) |
| ducking | with a voice-over the bed runs through `sidechaincompress` keyed on the narration, dropping it while someone speaks (measured ~7 dB at the default `duck` 12, ~8 dB at 24: the knob is a rough direction, not decibels); without narration the bed gets a plain gain and no compressor |
| loudness | two-pass `loudnorm`: pass 1 measures the mix, pass 2 corrects the whole mix by the measured offset (linear) to **-14 LUFS** integrated by default (`spec.audio.target_lufs`, -24..-12), LRA 11, true peak aimed at -1.5 dBTP with an `alimiter` ahead of pass 2 when the mix is too crest-heavy for linear mode — 0.5 dB under the verify ceiling so the AAC encoder's overshoot stays inside it |

`verify` re-measures the delivered MP4 (not the intermediate WAV) with `ffmpeg ebur128=peak=true` and
`silencedetect`, and reports `loudness = {integrated_lufs, lra_lu, true_peak_db}` plus `silences`. It is
an error when the integrated loudness is more than **1.5 LU** from the target (-14 by default), when the true peak is above
**-1.0 dBTP**, when the audio stream is not within **0.1 s** of the video duration, or when a narrated
video has more than **3 s** of silence (a gap the voice should have filled). A narrated spec whose mix
carries no voice-over (no narration track, because `narrate` was never run) is an error too: `no_voice`.

## Music credits
The render writes `/work/CREDITS.txt` next to the video (unlinked first, so no earlier video's credit
survives) and records it in the receipt: title, creator, licence, licence URL, source and the
`attribution` string `music-search` returned. `verify` echoes `music_license` and errors `credits_missing`
when the spec's track needs a credit and `CREDITS.txt` does not carry it — CC BY 4.0 makes the credit a
licence condition, so it ships in the video description.

**Content ID risk is unmitigated**: there is no allowlisted catalogue behind `/music` (no Pixabay/Mixkit
source), so a claimed video is possible on a perfectly licensed track. Keep the sidecar `music-search`
writes next to the audio (`license_evidence`, `source_url`, `sha256`) and use it in a dispute.

## Two plugin entries
| entry | network | exec tools |
|-------|---------|-----------|
| `storyboard-video` | host-reachable (`host.docker.internal`) | off |
| `storyboard-video-exec` | none, `--cap-drop ALL` (+`SETGID` for xterm) | on |

The exec entry needs `--cap-add SETGID`: without it xterm dies silently and a session recording never finds a window.

Both entries harden the container the same way: `--read-only`, `--cap-drop ALL`, `no-new-privileges`, `--pids-limit 256`, `--tmpfs /root` and **`--tmpfs /tmp:rw,exec`**. `/tmp` is exec on purpose: the previous engine's espeak G2P `dlopen`ed a library from it (Pocket TTS only writes a temp WAV there); `/work` is exec already, so the flag adds no real surface.

The image ships **no GTK/Qt**: inside the container a GUI capture is `xterm` or `xmessage`; a GTK/Qt app needs a custom image with its libraries.

Both mount `${PWD}:/repo:ro`, a named volume `storyboard-video-work:/work` and `${HOME}/.cache/storyboard-video/music:/music:ro` (the staged soundtrack, `music-search` writes it) and `${HOME}/.cache/storyboard-video/sfx:/sfx:ro` (staged library effects, `scene.sfx[].path`). **Start Claude Code from the repo root**: `${PWD}` is the launcher's working directory, not the project root — launched from `$HOME`, a desktop entry or an IDE, `/repo` is the wrong tree, and with `PWD` unset docker rejects `:/repo:ro`.

`STORYBOARD_MUSIC_DIR` / `STORYBOARD_SFX_DIR` relocate `/music` and `/sfx` inside the container.

**The mount is `${HOME}/.cache`, the stage is XDG**: `music-search` stages into `${XDG_CACHE_HOME:-~/.cache}/storyboard-video/music`, so if you set `XDG_CACHE_HOME` `fetch` returns a `mount_hint` — pass `--stage-dir "$HOME/.cache/storyboard-video/music"` (or change the `-v` source), or the track is staged where `/music` cannot see it (`music_path_missing`). Never mount `${HOME}` itself.

## Direction (the look, decided before the script)
`spec.direction` is the director's brief; `skills/storyboard-video` runs that step on the host (network, web research in `research`) and writes the same content to `/work/direction.md`. Every field has a reader, so nothing here is decoration:

| field | reader |
|---|---|
| `purpose` (`booth-loop`/`feature-demo`/`sales-video`/`other`), `tone`, `audio` (`voice`/`music`/`silent`) | the skill: which defaults, which beats, whether music/voice at all |
| `palette` + `palette_source` | `normalize` seeds `theme` with it (an explicit `spec.theme` still wins); `palette_contrast` errors on a pair under 4.5:1 (3:1 for the accent, 7:1 on body text for a `booth-loop`), and only **warns** when `palette_source` is `user` — a brand colour is the user's call |
| `motion` | `render`: `still` (the card never moves), `subtle` (**the default**) scales 0.98→1 in the first 0.8 s of a scene and then holds, `lively` is the old linear scale over the whole scene — the fix for text that looked like it kept growing |
| `pacing.max_words_card` | the `wordy` lint cap (18 without a direction) |
| `must_avoid` | `must_avoid` warns when one of the phrases shows up in on-screen text or narration |
| `research` | the user, in `direction.md`: `validate_spec` only checks it is a list — the items are never read and the render never fetches anything |
| `scenes` = `{<scene id>: {role, text, align, narration}}` | the writers (`role`/`text`/`align`), `render` (`align` → `c` vs `c center`), and `narration_off_plan` (error when a scene speaks against `narration:false`, warn the other way) |

The plan is best effort: `no_role` and `scene_unused` warn when it lags the timeline (a 4b cut or a `reframe` clone), so a stale plan never blocks a render. A spec with **no** `direction` keeps working exactly as before plus one `no_direction` warning, and `motion` defaults to `subtle` for it too. `RENDER_VERSION` is `4` (the timeline learned that the last scene pays no transition, and the template changed), so old stills and receipts are not reused.

## How it works
Scenes become an HTML timeline; Playwright (Chromium) seeks frame by frame and ffmpeg encodes. `validate_spec` writes the spec to `/work/specs/<hash>.json`; `stills`, `render` and `verify` all use that `spec_hash`, so editing the spec invalidates the review. Delivery renders are refused without stills. Text-only specs re-render deterministically (same spec ⇒ same frame digest); a scene with an `image` or a `video` can differ slightly between renders (≤ 8/255 luma, Chromium re-rasterising the asset), so its digest may change even though the pixels look identical.

## Limits
- Exec isolation is a container, not a VM; a repo with secrets in its tree is readable by the code you run. Don't enable exec on untrusted repos.
- Chromium is blocked from external URLs; web capture only allows localhost hosts.
- The mix is voice + music + optional `scene.sfx` (no per-scene music changes); a single `loudnorm` target (-14 LUFS by default) applies to the whole delivery, so a deliberately quiet ending is normalised away.
- Pocket TTS has 1 native pt-BR voice (`rafael`), the only one offered for `pt-BR`; the others are English speakers reading Portuguese and were dropped. `spec.say` is the lever when a word comes out wrong; there is no G2P to tune.
- `uncited_stat` needs a unit next to the number (`40%`, `8ms`); a bare integer on screen is not linted, so cite it yourself.

## Dev
`pip install -e . pytest && pytest tests`. Two optional dev scripts drive the shipped path: `scripts/storyboard-e2e.sh` runs the whole `plugin.json` entry end to end (real container, real render; `STORYBOARD_E2E_ENTRY` picks the `-exec` twin) and `scripts/check-release.py` asserts a published tag is the image this repo builds (`--self-test` runs offline). Neither is in CI. Outside Docker set `STORYBOARD_WORK`, `STORYBOARD_REPO` (and `STORYBOARD_MUSIC_DIR` if the soundtrack is not mounted at `/music`; it widens the read allowlist, operator-set only); Fedora ffmpeg lacks libx264 so the renderer falls back to openh264.
