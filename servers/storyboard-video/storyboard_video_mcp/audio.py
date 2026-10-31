"""The mix: a staged music bed + narration, ducked, normalised to -14 LUFS, encoded AAC 192k.

The bed is a track the music-search skill staged under /music (spec.music.path) and it is looped/trimmed
to the picture, faded in and out; under a voice-over it is compressed by `sidechaincompress` keyed on the
narration (a plain gain when nothing is spoken). The mix then goes through a two-pass `loudnorm` (measure,
then correct the whole mix by the measured offset) so the delivery sits at DEFAULT_TARGET_I (-14 LUFS, the
web/hero bar; `spec.audio.target_lufs` may pick another point in TARGET_RANGE) with true peaks under the
ceiling. `verify` re-measures the MP4 and reports the numbers, because the AAC encoder is the last thing
that touches the audio. The credit block for the published description is written next to the render
(`/work/CREDITS.txt` and `out/<resolved_hash>/CREDITS.txt`).
"""
from __future__ import annotations

import array
import json
import math
import statistics
import wave
import re
import subprocess
from pathlib import Path

from . import config, voices as _voices
from .safety import safe_path

DEFAULT_TARGET_I = -14.0  # EBU R128 integrated loudness of the delivery: the web/hero bar
TARGET_I = DEFAULT_TARGET_I  # kept as an alias: importers (and old tests) read the module constant
TARGET_RANGE = (-24.0, -12.0)  # spec.audio.target_lufs may move the target, but not out of this band
TARGET_TP = -1.5  # dBTP the normaliser aims at: 0.5 dB under the verify ceiling, for AAC overshoot
TARGET_LRA = 11.0
I_TOL = 1.5  # verify: how far the measured integrated loudness may sit from the target
# verify: true peak ceiling (dBTP) of the *encoded* file. Measured: the -1.5 dBTP the normaliser aims
# at comes out of AAC 192k at -1.3 dBTP on a voice+bed mix (and -1.0 on a plosive-heavy one), so the
# -1.5 ceiling this used to be would fail a correct render. The overshoot is the encoder's, not the mix's.
TP_LIMIT = -1.0
# How deep the look-ahead limiter in norm_chain may go before loudnorm's own dynamic mode is the lesser
# evil: past this the limiter is chewing the body of the speech, not clipping the transients.
LIMIT_FLOOR_DB = -12.0
# ...and how much peak the limiter may shave off. Measured: shaving 1.2 dB (crest 13.4) keeps the pass
# linear on target; shaving 5 dB (a bursty crest-19.5 mix) made it deliver -19 LUFS, worse than loudnorm's
# dynamic mode (-14.6). Past this the dynamic mode is the lesser evil.
MAX_SHAVE_DB = 3.0
MAX_SILENCE_S = 3.0  # verify: longest silence tolerated under a voice-over
SILENCE_DB = -45.0
FADE_IN_S, FADE_OUT_S = 1.5, 2.5
BITRATE = "192k"
SR = 48000


def bed(spec: dict) -> tuple[Path, dict] | None:
    """(file, levels) of the spec's staged track, or None when there is no (readable) music: a silent
    video is the default, so a missing file never fails a render."""
    m = spec.get("music")
    if not isinstance(m, dict) or not isinstance(m.get("path"), str) or not m["path"]:
        return None
    try:
        p = safe_path(m["path"], [config.MUSIC_DIR, config.WORK, config.REPO])
    except PermissionError:
        return None
    return (p, m) if p.is_file() else None


def bed_chain(total: float, volume_db: float, start_s: float = 0.0) -> str:
    """Trim the bed to `total` seconds from `start_s` (the skill picks the window), fade both ends, then
    set its level."""
    fi, fo = min(FADE_IN_S, total / 4), min(FADE_OUT_S, total / 4)
    trim = f"atrim=0:{total:.3f}" if not start_s else f"atrim=start={start_s:.3f}:end={start_s + total:.3f}"
    return (f"{trim},asetpts=N/SR/TB,afade=t=in:st=0:d={fi:.3f},"
            f"afade=t=out:st={total - fo:.3f}:d={fo:.3f},volume={volume_db:.2f}dB,"
            f"aresample={SR},aformat=channel_layouts=stereo")


def duck_chain(duck_db: float) -> str:
    """Duck the bed while the voice speaks. A voice line peaks around -20 dBFS, so against a low
    threshold a ratio of duck/6+1 removes roughly `duck_db` of gain."""
    r = max(1.2, min(20.0, duck_db / 6.0 + 1.0))
    return f"sidechaincompress=threshold=0.02:ratio={r:.2f}:attack=20:release=320:makeup=1:level_sc=1"


def mix_graph(total: float, voice: bool, has_bed: bool, volume_db: float = 0.0,
              duck_db: float = 12.0, start_s: float = 0.0, sfx: bool = False) -> str:
    """Filter graph for the mix, ending on [out]. Input 0 is the bed (when `has_bed`), input 1 the
    narration (when `voice`). The voice is only the sidechain *key*: it never gets compressed itself.
    With `sfx`, the last input is the effects track, added *after* the duck: it is neither ducked nor a
    key for the duck, or the bed would pump at every click. It needs a bed or a voice to sit on."""
    g = _mix_graph(total, voice, has_bed, volume_db, duck_db, start_s)
    if not sfx:
        return g
    i = int(voice) + int(has_bed)
    return (g.replace("[out]", "[pre]") + f";[{i}:a]aresample={SR},aformat=channel_layouts=stereo[fx];"
            f"[pre][fx]amix=inputs=2:normalize=0:duration=first:dropout_transition=0,"
            f"atrim=0:{total:.3f},asetpts=N/SR/TB[out]")


def _mix_graph(total: float, voice: bool, has_bed: bool, volume_db: float, duck_db: float, start_s: float) -> str:
    v = f"aresample={SR},aformat=channel_layouts=stereo,apad"
    tail = f"apad,atrim=0:{total:.3f},asetpts=N/SR/TB[out]"
    if has_bed and voice:
        return (f"[0:a]{bed_chain(total, volume_db, start_s)}[bed];"
                f"[1:a]{v},asplit=2[voice][key];"
                f"[bed][key]{duck_chain(duck_db)}[ducked];"
                f"[ducked][voice]amix=inputs=2:normalize=0:dropout_transition=0,{tail}")
    if has_bed:
        return f"[0:a]{bed_chain(total, volume_db, start_s)},{tail}"
    return f"[0:a]{v},{tail}"


def build(spec: dict, narration: Path | None, total: float, out: Path, sfx: Path | None = None) -> Path | None:
    """Write the un-normalised mix to `out` (48 kHz stereo PCM). None when there is nothing to mix."""
    b = bed(spec)
    if not narration and not b:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if b:
        cmd += ["-stream_loop", "-1", "-i", str(b[0])]  # a 3 min track, a 30 s video: loop it
    if narration:
        cmd += ["-i", str(narration)]
    if sfx:
        cmd += ["-i", str(sfx)]
    cmd += ["-filter_complex",
            mix_graph(total, bool(narration), bool(b),
                      float((b[1] if b else {}).get("volume_db", 0.0)),
                      float((b[1] if b else {}).get("duck", 12.0)),
                      float((b[1] if b else {}).get("start_s") or 0.0), bool(sfx)),
            "-map", "[out]", "-t", f"{total:.3f}", "-ar", str(SR), "-ac", "2",
            "-c:a", "pcm_s16le", str(out)]
    subprocess.run(cmd, check=True)
    return out


DUCK_MARGIN_MIN_DB = 8.0  # the voice should sit at least this far above the bed while it speaks
WIN_S = 0.1


def duck_margin_db(spec: dict, narration: Path | None, total: float) -> float | None:
    """How far the voice sits above the *ducked* bed while it speaks (median over 100 ms windows where the
    voice is audible), measured on the two stems before normalisation -- both scale together, so the gap
    is what the listener gets. None without a bed and a voice."""
    b = bed(spec)
    if not (b and narration):
        return None
    m, d = b[1], narration.parent
    g = (f"[0:a]{bed_chain(total, float(m.get('volume_db', 0.0)), float(m.get('start_s') or 0.0))}[bed];"
         f"[1:a]aresample={SR},aformat=channel_layouts=stereo,apad,asplit=2[voice][key];"
         f"[bed][key]{duck_chain(float(m.get('duck', 12.0)))}[duck];"
         # shortcut: 0.5/0.5 downmix reads a wide, uncorrelated stereo bed up to ~3 dB low; upgrade if a bed shows it
         f"[duck]atrim=0:{total:.3f},aresample=8000,pan=mono|c0=0.5*c0+0.5*c1[b];"
         f"[voice]atrim=0:{total:.3f},aresample=8000,pan=mono|c0=0.5*c0+0.5*c1[v]")
    pb, pv = d / "stem-bed.wav", d / "stem-voice.wav"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(b[0]), "-i", str(narration),
                        "-filter_complex", g, "-map", "[b]", "-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(pb),
                        "-map", "[v]", "-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(pv)], capture_output=True)
    if r.returncode:
        return None
    try:
        gaps = _stem_gaps(pb, pv)
    finally:
        pb.unlink(missing_ok=True)
        pv.unlink(missing_ok=True)
    return round(statistics.median(gaps), 1) if gaps else None


def _stem_gaps(pb: Path, pv: Path) -> list[float]:
    def db(path):
        with wave.open(str(path), "rb") as w:
            x = array.array("h")
            x.frombytes(w.readframes(w.getnframes()))
            n = int(w.getframerate() * WIN_S)
        return [20 * math.log10(max(1e-5, math.sqrt(sum(v * v for v in x[i:i + n]) / n) / 32768))
                for i in range(0, len(x) - n + 1, n)]
    b, v = db(pb), db(pv)
    return [vv - bb for vv, bb in zip(v, b) if vv > -40.0]


def _num(s: str) -> float | None:
    return None if s.strip().lower().startswith(("-inf", "inf", "nan")) else float(s)


def parse_ebur128(err: str) -> dict | None:
    """Integrated LUFS / LRA / true peak out of ffmpeg's `ebur128=peak=true` Summary block."""
    tail = err.rsplit("Summary:", 1)[-1] if "Summary:" in err else ""
    i = re.search(r"^\s+I:\s+(\S+) LUFS", tail, re.M)
    if not i:
        return None
    lra = re.search(r"^\s+LRA:\s+(\S+) LU", tail, re.M)
    pk = re.search(r"^\s+Peak:\s+(\S+) dBFS", tail, re.M)
    return {"integrated_lufs": _num(i.group(1)), "lra_lu": _num(lra.group(1)) if lra else None,
            "true_peak_db": _num(pk.group(1)) if pk else None}


def measure_r128(path: str) -> dict | None:
    """EBU R128 of a file as ffmpeg measures it (the same number a broadcaster would read)."""
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    return parse_ebur128(r.stderr)


def parse_loudnorm_json(err: str) -> dict:
    """The measurement block loudnorm prints on its first (analysis) pass."""
    m = None
    for m in re.finditer(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S):
        pass
    if not m:
        return {}
    j = json.loads(m.group(0))
    out = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            out[k] = float(j[k])
        except (KeyError, TypeError, ValueError):
            return {}
    return out


def target_lufs(spec: dict) -> float:
    """The delivery loudness target this spec asks for: `spec.audio.target_lufs`, else DEFAULT_TARGET_I.
    Raises ValueError outside TARGET_RANGE (-24..-12): a target the loudnorm pass cannot honour is a spec
    bug, and silently delivering the default would hide it."""
    au = spec.get("audio")
    if au is None:
        return DEFAULT_TARGET_I
    if not isinstance(au, dict):
        raise ValueError(f"spec.audio {au!r} is not an object; use audio = {{target_lufs: -14}}")
    v = au.get("target_lufs")
    if v is None:
        return DEFAULT_TARGET_I
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"spec.audio.target_lufs {v!r} is not a number "
                         f"({TARGET_RANGE[0]:g}..{TARGET_RANGE[1]:g} LUFS)")
    return _target(v)


def _target(target_i: float | None) -> float:
    """Coerce/validate an explicit target (None keeps the default); the single rule every entry point uses."""
    t = DEFAULT_TARGET_I if target_i is None else float(target_i)
    lo, hi = TARGET_RANGE
    if not lo <= t <= hi:  # also rejects NaN
        raise ValueError(f"target_lufs {t:g} is outside {lo:g}..{hi:g} LUFS")
    return t


def measure_loudnorm(path: str, target_i: float | None = None) -> dict:
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-af",
                        f"loudnorm=I={_target(target_i):.1f}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    return parse_loudnorm_json(r.stderr)


def limiter_db(ln: dict, target_i: float | None = None) -> float | None:
    """How hard a look-ahead limiter has to hit (dB, negative) for the second loudnorm pass to stay
    linear, or None when it already fits or would have to squash the mix past LIMIT_FLOOR_DB.

    `loudnorm linear=true` only stays linear if the gain the mix needs (target - measured I) raised onto
    the measured true peak still lands under TP; otherwise it silently switches to dynamic mode, which
    pumps. Measured on ffmpeg 8.1 with a voice+bed mix: crest factor (TP - I) 13.4 dB stays linear at
    -16 (-15.74 LUFS / -2.35 dBTP) and goes dynamic at -14 (-14.06 / -1.50, LRA 8.4 -> 8.1), i.e. the
    linear window is crest <= 14.5 dB at -16 and <= 12.5 dB at -14. Clamping the peaks at TP - gain keeps
    the gain, and with it the dynamics, where the mix left them."""
    ti = _target(target_i)
    if not ln:
        return None
    gain = ti - ln["input_i"]
    if ln["input_tp"] + gain <= TARGET_TP:  # linear already fits: never touch the audio
        return None
    if ln["input_tp"] + gain - TARGET_TP > MAX_SHAVE_DB:
        return None
    lim = TARGET_TP - gain  # peaks clamped here land exactly on TARGET_TP once the gain is applied
    return round(lim, 2) if lim >= LIMIT_FLOOR_DB else None


def norm_chain(ln: dict, target_i: float | None = None) -> str:
    """Second loudnorm pass: correct the whole mix by the measured offset (linear), not by squashing it.

    When the mix's peaks would not survive that gain (see limiter_db) an `alimiter` goes in front and the
    pass is told the peak it will actually see after limiting, so loudnorm keeps `linear=true` instead of
    quietly switching to its dynamic mode. `level=false`: the limiter must not add makeup gain of its own."""
    ti = _target(target_i)
    chain = f"loudnorm=I={ti:.1f}:TP={TARGET_TP}:LRA={TARGET_LRA}"
    if ln:
        lim = limiter_db(ln, ti)
        peak = min(ln["input_tp"], lim) if lim is not None else ln["input_tp"]
        pre = f"alimiter=limit={10 ** (lim / 20):.4f}:level=false," if lim is not None else ""
        chain = (f"{pre}{chain}:measured_I={ln['input_i']}:measured_TP={peak}"
                 f":measured_LRA={ln['input_lra']}:measured_thresh={ln['input_thresh']}"
                 f":offset={ln['target_offset']}:linear=true")
    return f"{chain},aresample={SR}"


def mux_cmd(mp4: Path, wav: Path, total: float, chain: str) -> list[str]:
    """Picture copied untouched (it is already encoded), audio normalised and encoded to AAC 192k."""
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-i", str(wav),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", chain, "-c:a", "aac",
            "-b:a", BITRATE, "-ar", str(SR), "-t", f"{total:.3f}", "-movflags", "+faststart"]


def mux(mp4: Path, spec: dict, narration: Path | None, total: float,
        target_i: float | None = None, wav: Path | None = None, sfx: Path | None = None) -> dict | None:
    """Mix + two-pass loudnorm + mux into `mp4` in place. None when the spec has no audio at all. The
    target is `target_i` when given, else what the spec asks for (`spec.audio.target_lufs`)."""
    ti = target_lufs(spec) if target_i is None else _target(target_i)
    b = bed(spec)
    wav = build(spec, narration, total, wav or mp4.parent / "mix.wav", sfx)
    if not wav:
        return None
    ln = measure_loudnorm(str(wav), ti)
    tmp = mp4.with_name(mp4.stem + ".mux.mp4")
    subprocess.run([*mux_cmd(mp4, wav, total, norm_chain(ln, ti)), str(tmp)], check=True)
    tmp.replace(mp4)
    return {"mix": str(wav), "voice": bool(narration), "music": (b[1].get("path") if b else None),
            "license": (b[1].get("license") if b else None), "start_s": (b[1].get("start_s") if b else None),
            "volume_db": (b[1].get("volume_db") if b else None),
            "ducked": bool(narration and b), "target_lufs": ti, "loudnorm": ln or None,
            "sfx": bool(sfx), "duck_margin_db": duck_margin_db(spec, narration, total)}


def credits_text(spec: dict, target_i: float | None = None) -> str | None:
    """The credit block for the published description: title, creator, licence + link, source and the
    attribution the skill returned (mandatory for CC BY). None when the spec has no track.

    `target_i` is opt-in: when given, the block also states the loudness the mix was mastered to. It is
    not filled in by default because CREDITS.txt is written before verify measures the delivery, and a
    credit that claims a level the render did not reach would be a lie in the published description."""
    m = spec.get("music")
    ti = _target(target_i) if target_i is not None else None  # validated before the no-track shortcut
    from . import sfx as _sfx
    fx = _sfx.credits(spec) if isinstance(spec.get("scenes"), list) else []
    vc = _voices.credits(spec)
    if not isinstance(m, dict) or not m.get("path"):
        parts = (["Sound effect credits", *fx] if fx else []) + (["Voice credits", *vc] if vc else [])
        return "\n".join(parts) + "\n" if parts else None
    who = " by ".join(str(x) for x in (m.get("title"), m.get("creator")) if x)
    head = " · ".join(str(x) for x in (who, m.get("license"), m.get("license_url"), m.get("source_url")) if x)
    lines = ["Music credits", f"- {head}" if head else "- (unnamed track)"]
    if str(m.get("attribution") or "").strip():
        lines.append("  " + str(m["attribution"]).strip().replace("\n", "\n  "))
    if fx:
        lines += ["Sound effect credits", *fx]
    if vc:
        lines += ["Voice credits", *vc]
    if ti is not None:
        lines.append(f"- Audio mastered to {ti:.0f} LUFS integrated")
    return "\n".join(lines) + "\n"


def write_credits(spec: dict, out: Path | None = None, target_i: float | None = None) -> str | None:
    """Write CREDITS.txt for this render, both in /work (what the skill and the user read) and next to
    the video (`out`), because a later render — even a silent one — unlinks /work/CREDITS.txt and an
    older receipt must still point at its own credit. Unlinked first, so a previous video's credit
    never survives into this one. Returns the /work path, or None when there is nothing to credit."""
    text = credits_text(spec, target_i)
    paths = [config.WORK / "CREDITS.txt"] + ([out / "CREDITS.txt"] if out else [])
    for p in paths:
        p.unlink(missing_ok=True)
        if text is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    return str(paths[0]) if text is not None else None


def parse_silences(err: str, total: float) -> list[dict]:
    """silencedetect output as [{start_s, end_s, duration_s}]; a silence still open at EOF ends at `total`."""
    out, start = [], None
    for m in re.finditer(r"silence_(start|end):\s*(-?[\d.]+)", err):
        kind, t = m.group(1), float(m.group(2))
        if kind == "start":
            start = t
        elif start is not None:
            out.append({"start_s": round(start, 3), "end_s": round(t, 3), "duration_s": round(t - start, 3)})
            start = None
    if start is not None and total > start:
        out.append({"start_s": round(start, 3), "end_s": round(total, 3), "duration_s": round(total - start, 3)})
    return out


def silences(path: str, total: float, min_s: float = 1.0) -> list[dict]:
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-af",
                        f"silencedetect=n={SILENCE_DB}dB:d={min_s}", "-f", "null", "-"],
                       capture_output=True, text=True)
    return parse_silences(r.stderr, total)


def loudness_findings(m: dict | None, voiced: bool, sil: list[dict],
                      target_i: float | None = None) -> list[dict]:
    """The delivery bar: the spec's target (default -14) +-1.5 LU, true peak under TP_LIMIT dBTP, no dead
    air under a voice-over."""
    ti = _target(target_i)
    f: list[dict] = []
    if not m or m.get("integrated_lufs") is None:
        return [{"severity": "error", "code": "no_loudness",
                 "message": "could not measure EBU R128 loudness of the audio stream"}]
    i = m["integrated_lufs"]
    if abs(i - ti) > I_TOL:
        f.append({"severity": "error", "code": "loudness",
                  "message": f"{i:.1f} LUFS is more than {I_TOL} LU from {ti:.0f} LUFS"})
    tp = m.get("true_peak_db")
    if tp is not None and tp > TP_LIMIT:
        f.append({"severity": "error", "code": "true_peak",
                  "message": f"true peak {tp:.1f} dBTP is above the {TP_LIMIT} dBTP ceiling"})
    if voiced:
        long = [s for s in sil if s["duration_s"] > MAX_SILENCE_S]
        if long:
            f.append({"severity": "error", "code": "long_silence",
                      "message": f"{long[0]['duration_s']:.1f}s of silence at {long[0]['start_s']:.1f}s "
                                 f"(max {MAX_SILENCE_S}s in a narrated video)"})
    return f


def check(path: str, total: float, voiced: bool, target_i: float | None = None) -> dict:
    """Measure a rendered MP4's audio the way verify reports it, against `target_i` (default -14)."""
    ti = _target(target_i)
    m = measure_r128(path)
    sil = silences(path, total) if voiced else []
    return {"loudness": m, "silences": sil, "findings": loudness_findings(m, voiced, sil, ti)}
