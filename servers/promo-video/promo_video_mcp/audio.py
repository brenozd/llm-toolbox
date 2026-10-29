"""The mix: bundled music bed + narration, ducked, normalised to -16 LUFS, encoded AAC 192k.

The bed is looped/trimmed to the picture and faded in and out; under a voice-over it is compressed by
`sidechaincompress` keyed on the narration (a plain gain when nothing is spoken). The mix then goes
through a two-pass `loudnorm` (measure, then correct the whole mix by the measured offset) so the
delivery sits at -16 LUFS integrated with true peaks under the ceiling. `verify` re-measures the MP4
and reports the numbers, because the AAC encoder is the last thing that touches the audio.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import music as M

TARGET_I = -16.0  # EBU R128 integrated loudness of the delivery
TARGET_TP = -2.0  # dBTP the normaliser aims at: 0.5 dB under the verify ceiling, for AAC overshoot
TARGET_LRA = 11.0
I_TOL = 1.5  # verify: how far the measured integrated loudness may sit from TARGET_I
TP_LIMIT = -1.5  # verify: true peak ceiling (dBTP)
MAX_SILENCE_S = 3.0  # verify: longest silence tolerated under a voice-over
SILENCE_DB = -45.0
FADE_IN_S, FADE_OUT_S = 1.5, 2.5
BITRATE = "192k"
SR = 48000


def bed(spec: dict) -> tuple[Path, dict] | None:
    """(file, levels) of the spec's bundled track, or None when there is no (available) music."""
    m = spec.get("music")
    if not isinstance(m, dict) or not m.get("id"):
        return None
    t = M.get(m["id"])
    p = M.path_of(t) if t else None
    return (p, m) if p else None


def bed_chain(total: float, volume_db: float) -> str:
    """Loop/trim the bed to the picture, fade both ends, then set its level."""
    fi, fo = min(FADE_IN_S, total / 4), min(FADE_OUT_S, total / 4)
    return (f"atrim=0:{total:.3f},asetpts=N/SR/TB,afade=t=in:st=0:d={fi:.3f},"
            f"afade=t=out:st={total - fo:.3f}:d={fo:.3f},volume={volume_db:.2f}dB,"
            f"aresample={SR},aformat=channel_layouts=stereo")


def duck_chain(duck_db: float) -> str:
    """Duck the bed while the voice speaks. A voice line peaks around -20 dBFS, so against a low
    threshold a ratio of duck/6+1 removes roughly `duck_db` of gain."""
    r = max(1.2, min(20.0, duck_db / 6.0 + 1.0))
    return f"sidechaincompress=threshold=0.02:ratio={r:.2f}:attack=20:release=320:makeup=1:level_sc=1"


def mix_graph(total: float, voice: bool, has_bed: bool, volume_db: float = 0.0,
              duck_db: float = 12.0) -> str:
    """Filter graph for the mix, ending on [out]. Input 0 is the bed (when `has_bed`), input 1 the
    narration (when `voice`). The voice is only the sidechain *key*: it never gets compressed itself."""
    v = f"aresample={SR},aformat=channel_layouts=stereo,apad"
    tail = f"apad,atrim=0:{total:.3f},asetpts=N/SR/TB[out]"
    if has_bed and voice:
        return (f"[0:a]{bed_chain(total, volume_db)}[bed];"
                f"[1:a]{v},asplit=2[voice][key];"
                f"[bed][key]{duck_chain(duck_db)}[ducked];"
                f"[ducked][voice]amix=inputs=2:normalize=0:dropout_transition=0,{tail}")
    if has_bed:
        return f"[0:a]{bed_chain(total, volume_db)},{tail}"
    return f"[0:a]{v},{tail}"


def build(spec: dict, narration: Path | None, total: float, out: Path) -> Path | None:
    """Write the un-normalised mix to `out` (48 kHz stereo PCM). None when there is nothing to mix."""
    b = bed(spec)
    if not narration and not b:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if b:
        cmd += ["-stream_loop", "-1", "-i", str(b[0])]  # a 5 min track, a 30 s video: loop it
    if narration:
        cmd += ["-i", str(narration)]
    cmd += ["-filter_complex",
            mix_graph(total, bool(narration), bool(b),
                      float((b[1] if b else {}).get("volume_db", 0.0)),
                      float((b[1] if b else {}).get("duck", 12.0))),
            "-map", "[out]", "-t", f"{total:.3f}", "-ar", str(SR), "-ac", "2",
            "-c:a", "pcm_s16le", str(out)]
    subprocess.run(cmd, check=True)
    return out


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


def measure_loudnorm(path: str) -> dict:
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-af",
                        f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    return parse_loudnorm_json(r.stderr)


def norm_chain(ln: dict) -> str:
    """Second loudnorm pass: correct the whole mix by the measured offset (linear), not by squashing it."""
    chain = f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}"
    if ln:
        chain += (f":measured_I={ln['input_i']}:measured_TP={ln['input_tp']}:measured_LRA={ln['input_lra']}"
                  f":measured_thresh={ln['input_thresh']}:offset={ln['target_offset']}:linear=true")
    return f"{chain},aresample={SR}"


def mux_cmd(mp4: Path, wav: Path, total: float, chain: str) -> list[str]:
    """Picture copied untouched (it is already encoded), audio normalised and encoded to AAC 192k."""
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-i", str(wav),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", chain, "-c:a", "aac",
            "-b:a", BITRATE, "-ar", str(SR), "-t", f"{total:.3f}", "-movflags", "+faststart"]


def mux(mp4: Path, spec: dict, narration: Path | None, total: float) -> dict | None:
    """Mix + two-pass loudnorm + mux into `mp4` in place. None when the spec has no audio at all."""
    b = bed(spec)
    wav = build(spec, narration, total, mp4.parent / "mix.wav")
    if not wav:
        return None
    ln = measure_loudnorm(str(wav))
    tmp = mp4.with_name(mp4.stem + ".mux.mp4")
    subprocess.run([*mux_cmd(mp4, wav, total, norm_chain(ln)), str(tmp)], check=True)
    tmp.replace(mp4)
    return {"mix": str(wav), "voice": bool(narration), "music": (b[1].get("id") if b else None),
            "volume_db": (b[1].get("volume_db") if b else None),
            "ducked": bool(narration and b), "target_lufs": TARGET_I, "loudnorm": ln or None}


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


def loudness_findings(m: dict | None, voiced: bool, sil: list[dict]) -> list[dict]:
    """The delivery bar: -16 LUFS +-1.5 LU, true peak under -1.5 dBTP, no dead air under a voice-over."""
    f: list[dict] = []
    if not m or m.get("integrated_lufs") is None:
        return [{"severity": "error", "code": "no_loudness",
                 "message": "could not measure EBU R128 loudness of the audio stream"}]
    i = m["integrated_lufs"]
    if abs(i - TARGET_I) > I_TOL:
        f.append({"severity": "error", "code": "loudness",
                  "message": f"{i:.1f} LUFS is more than {I_TOL} LU from {TARGET_I:.0f} LUFS"})
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


def check(path: str, total: float, voiced: bool) -> dict:
    """Measure a rendered MP4's audio the way verify reports it."""
    m = measure_r128(path)
    sil = silences(path, total) if voiced else []
    return {"loudness": m, "silences": sil, "findings": loudness_findings(m, voiced, sil)}
