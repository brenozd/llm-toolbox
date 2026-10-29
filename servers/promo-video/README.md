# promo-video MCP

Builds a captioned promo video (MP4 + SRT + poster) from a repo, with every claim tied to a capture or `file:line`, plus an offline voice-over.
Works for web, CLI and GUI projects. Pair it with [`skills/promo-video`](../../skills/promo-video/).

## Tools
`preflight`, `scan_repo`, `brand_tokens`, `extract_code`, `capture_web`, `capture_terminal`*, `capture_terminal_session`*, `capture_gui`*, `list_music`, `validate_spec`, `narrate`, `stills`, `audit_layout`, `reframe`, `render` + `render_status`, `verify`.
(*) run repo code: only enabled when the container has `PROMO_ALLOW_EXEC=1`, which the operator sets (plugin entry `promo-video-exec`), not the model.

## 16:9 and 9:16
Every capture tool takes `aspect` (`16:9` default, or `9:16`) and fills in that format's geometry, because the format is baked into the pixels: a landscape screenshot letterboxes in a portrait frame.

| aspect | web viewport | session cols x rows | gui screen | terminal cols |
|--------|--------------|---------------------|------------|---------------|
| `16:9` | 1440x810 (dsf 1) | 80x16 | 1280x720 | 100 |
| `9:16` | 540x960 (dsf 2) | 44x28 | 720x1280 | 40 |

The session grid's aspect is picked to match the content box (16:9 window 1444x633 in a 1587x755 box), so a recording fills the frame width instead of sitting in the middle as a small stamp.

Portrait keeps the top 10% / bottom 20% / sides 5% clear (the bands a phone UI covers): the content box is padded past both bands and the caption sits just above the bottom one. `reframe(spec_hash, aspect)` clones a spec into the other aspect, applies the portrait rules (max 4 bullets, terminal lines trimmed to ~40 cols, every lossy edit reported) and lists the captures whose geometry no longer matches, with the call that redoes them.

Images cover the frame and centre `scene.focus` instead of letterboxing: `layout.zoom_plan` clamps the pan to what the capture can cover and the zoom so the focus stays in shot. `stills` and `audit_layout` measure every text box of every scene (`getBoundingClientRect`) and warn when a box leaves the frame, sits in a safe zone, or is clipped inside its own box.

## Real terminal sessions
`capture_terminal_session` records a genuine session: Xvfb → xterm (no scrollbar) → `bash`, with every keystroke sent by `xdotool` and the screen grabbed by ffmpeg `x11grab`.
**The typing speed is staged** (`delay_ms` + seeded jitter); **the output is real** — the shell really runs the command and the MP4 is a recording of it, not an animation.
`steps` = `[{type:'type',text}|{type:'key',key}|{type:'wait_for',text,timeout_s}|{type:'hold_s',s}]`; `wait_for` polls the pty log and a timeout fails the take (no half clip). The MP4, a poster PNG and `session.json` (steps, seed, output text) land in `/work/captures/<id>/`. A `terminal` scene plays it inside a fake window title bar.
The image also ships **gcc + libc6-dev**, so a CLI demo can compile its own sample program inside the exec container and show the real compile (`gcc -O0 -o leak leak.c`) instead of shipping a binary.

## Voice-over (offline)
`list_music(mood?)` lists the bundled soundtrack: five **CC0 / public-domain** tracks (`music/catalog.json`, populated by `scripts/fetch_music.py`, which refuses any license that is not CC0 or PD and sha256-checks every download). `spec.music = {"id", "volume_db", "duck"}` is linted against it (`unknown_music`); the render mixes it (see **Mix and loudness**).

`narrate(spec_hash)` synthesizes every `scene.narration` with Kokoro-82M (`kokoro-onnx`, Apache-2.0 weights; espeak-ng G2P for `pt-BR` and `en`) into one WAV per scene under `/work/audio/<spec_hash>/`, plus a `manifest.json` with the durations measured from the files. The model and the 54-voice pack are baked into the image and sha256-checked at build time: no network, no torch. Cache key = `text + voice + speed + lang + model identity (name:size)` and `resolved_hash` also carries `RENDER_VERSION`, so a re-baked model or a template change invalidates the cached WAVs/stills.
A scene then lasts `max(duration_s, audio + 0.4 s)`, and `spec.timeline()` reads the manifest — so the *resolved* hash (`spec_hash` + audio digest) changes when the speech changes, and old stills/renders are never reused (delivery is refused until you re-run `stills`).
`spec.lang` (`pt-BR`|`en`) is required as soon as a scene has narration; `spec.voice` overrides the default (`pf_dora` / `af_heart`). `spec.say = {"LD_PRELOAD": "el di preload"}` is applied to the text *before* synthesis: `lint` warns (`say_missing`) for every acronym, snake_case/camelCase token or on-screen identifier a scene speaks without a mapping, and for speech faster than ~3.2 words/s (`narration_pace`). Spoken numbers need `scene.evidence` like any other claim.

## Mix and loudness
The render builds one soundtrack per video (`promo_video_mcp/audio.py`), then muxes it: the picture is
copied untouched, the audio becomes **AAC 192 kbit/s** 48 kHz stereo, exactly as long as the picture.

| layer | what it does |
|---|---|
| music bed (`spec.music`) | the bundled track is looped/trimmed to the video length, faded in 1.5 s and out 2.5 s (both clamped to a quarter of a short video), then set to `volume_db` (default -18 dB) |
| narration | each scene's WAV laid at its scene offset (`narration_track`) |
| ducking | with a voice-over the bed runs through `sidechaincompress` keyed on the narration, dropping it while someone speaks (measured ~7 dB at the default `duck` 12, ~8 dB at 24: the knob is a rough direction, not decibels); without narration the bed gets a plain gain and no compressor |
| loudness | two-pass `loudnorm`: pass 1 measures the mix, pass 2 corrects the whole mix by the measured offset (linear) to **-16 LUFS** integrated, LRA 11, true peak aimed at -2.0 dBTP — 0.5 dB under the verify ceiling so the AAC encoder's overshoot stays inside it |

`verify` re-measures the delivered MP4 (not the intermediate WAV) with `ffmpeg ebur128=peak=true` and
`silencedetect`, and reports `loudness = {integrated_lufs, lra_lu, true_peak_db}` plus `silences`. It is
an error when the integrated loudness is more than **1.5 LU** from -16 LUFS, when the true peak is above
**-1.5 dBTP**, when the audio stream is not within **0.1 s** of the video duration, or when a narrated
video has more than **3 s** of silence (a gap the voice should have filled). A narrated spec whose mix
carries no voice-over (the music bed alone, because `narrate` was never run) is an error too: `no_voice`.

Licences of the bundled tracks (all **CC0 1.0 or public domain**, verified on the origin page and
sha256-pinned in `music/catalog.json`; `scripts/fetch_music.py` refuses anything else, so no attribution
is ever required):

| id | title | licence | source |
|---|---|---|---|
| `moonlight-sonata` | Beethoven, Moonlight Sonata (1st mvt, MIDI rendering) | Public domain | Wikimedia Commons |
| `hallelujah-chorus-1916` | Handel, Hallelujah Chorus (Edison, 1916) | Public domain | Wikimedia Commons |
| `sultana-1908` | Chiquinha Gonzaga, Sultana (1908) | Public domain | Wikimedia Commons |
| `chopin-mazurka-op17-3` | Chopin, Mazurka Op. 17 No. 3 (Musopen) | CC0 1.0 | Internet Archive |
| `chill-main-menu` | Augmentality, Chill Main Menu music | CC0 1.0 (dual OGA-BY/CC0; CC0 elected) | OpenGameArt |

## Two plugin entries
| entry | network | exec tools |
|-------|---------|-----------|
| `promo-video` | host-reachable (`host.docker.internal`) | off |
| `promo-video-exec` | none, `--cap-drop ALL` (+`SETGID` for xterm) | on |

The exec entry needs `--cap-add SETGID`: without it xterm dies silently and a session recording never finds a window.

Both mount `${PWD}:/repo:ro` and a named volume `promo-video-work:/work`. Never mount `${HOME}`.

## How it works
Scenes become an HTML timeline; Playwright (Chromium) seeks frame by frame and ffmpeg encodes. `validate_spec` writes the spec to `/work/specs/<hash>.json`; `stills`, `render` and `verify` all use that `spec_hash`, so editing the spec invalidates the review. Delivery renders are refused without stills. Text-only specs re-render deterministically (same spec ⇒ same frame digest); a scene with an `image` or a `video` can differ slightly between renders (≤ 8/255 luma, Chromium re-rasterising the asset), so its digest may change even though the pixels look identical.

## Limits
- Exec isolation is a container, not a VM; a repo with secrets in its tree is readable by the code you run. Don't enable exec on untrusted repos.
- Chromium is blocked from external URLs; web capture only allows localhost hosts.
- The mix is voice + music only (no SFX, no per-scene music changes); a single `loudnorm` target (-16 LUFS) applies to the whole delivery, so a deliberately quiet ending is normalised away.
- Kokoro's pt-BR voices are intelligible but not native-sounding; `spec.say` is the lever when a word comes out wrong.

## Dev
`pip install -e . pytest && pytest tests`. Outside Docker set `PROMO_WORK`, `PROMO_REPO`; Fedora ffmpeg lacks libx264 so the renderer falls back to openh264.
