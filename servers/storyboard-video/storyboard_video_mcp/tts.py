"""Offline narration: Kokoro-82M (Apache-2.0) through kokoro-onnx, one WAV per narrated scene.

The model and voices are baked into the image (no runtime download). Synthesis is cached on
text+voice+speed+lang, so re-running narrate only pays for the lines that actually changed.
"""
from __future__ import annotations

import array
import hashlib
import json
import os
import re
import wave
from pathlib import Path

from . import config, spec as S

# spec.lang -> (kokoro lang code, default voice). Voices: pf_dora is the pt-BR female voice,
# af_heart the top-graded English one; both ship in voices-v1.0.bin.
LANGS = {"pt-BR": ("pt-br", "pf_dora"), "en": ("en-us", "af_heart")}
MODEL = os.environ.get("STORYBOARD_KOKORO_MODEL", "/opt/kokoro/kokoro-v1.0.fp16.onnx")
VOICES = os.environ.get("STORYBOARD_KOKORO_VOICES", "/opt/kokoro/voices-v1.0.bin")

_ENGINE = None


def _engine():
    """Load kokoro once per process; tests monkeypatch this with a fake engine."""
    global _ENGINE
    if _ENGINE is None:
        for p in (MODEL, VOICES):
            if not Path(p).is_file():
                raise FileNotFoundError(f"TTS model missing: {p} (baked into the image at build time)")
        from kokoro_onnx import Kokoro
        _ENGINE = Kokoro(MODEL, VOICES)
    return _ENGINE


def pronounce(text: str, say: dict | None) -> str:
    """Apply spec.say to the text *before* synthesis: TTS mangles identifiers, so the author
    spells the spoken form ('LD_PRELOAD' -> 'el di preload'). Longest key first, whole tokens
    only, so a mapping for 'go' never rewrites 'gopher'."""
    for k in sorted(say or {}, key=len, reverse=True):
        if not k:
            continue
        text = re.sub(rf"(?<![\w-]){re.escape(k)}(?![\w-])", lambda _m, v=str(say[k]): v, text)
    return text


def cache_key(text: str, voice: str, speed: float, lang: str) -> str:
    """text+voice+speed+lang *and* the model file identity: re-baking the model must invalidate the
    WAVs the previous one synthesized (same text, different voice)."""
    return hashlib.sha256(f"{text}\x00{voice}\x00{speed:.3f}\x00{lang}\x00{config.model_id()}".encode()).hexdigest()[:16]


def _pcm(samples) -> bytes:
    if hasattr(samples, "astype"):  # numpy fast path
        return (samples.clip(-1.0, 1.0) * 32767).astype("<i2").tobytes()
    return array.array("h", (max(-32768, min(32767, int(s * 32767))) for s in samples)).tobytes()


def _write_wav(path: Path, samples, sr: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(_pcm(samples))


def wav_seconds(path: Path) -> float:
    """Real duration from the file itself: the timeline must use what was spoken, not an estimate."""
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


def _voice_of(spec: dict, sc: dict) -> str:
    return sc.get("voice") or spec.get("voice") or LANGS[spec["lang"]][1]


def narrate(h: str) -> dict:
    """Synthesize every narrated scene of spec `h` into /work/audio/<h>/, one WAV per scene, and
    write manifest.json with the measured durations that spec.timeline() then uses."""
    spec = S.load(h)
    scenes = [sc for sc in spec["scenes"] if isinstance(sc.get("narration"), str) and sc["narration"].strip()]
    lang = spec.get("lang")
    if lang not in LANGS:
        raise ValueError(f"spec.lang must be one of {sorted(LANGS)} to narrate (got {lang!r})")
    d = config.WORK / "audio" / h
    d.mkdir(parents=True, exist_ok=True)
    man = {"spec_hash": h, "lang": lang, "scenes": {}}
    eng, made = None, 0
    for sc in scenes:
        voice = _voice_of(spec, sc)
        speed = float(sc.get("speed") or spec.get("speed") or 1.0)
        text = pronounce(sc["narration"], spec.get("say"))
        key = cache_key(text, voice, speed, lang)
        p = d / f"{sc['id']}-{key}.wav"  # scene id in the name: identical lines keep separate files
        if not p.exists():
            eng = eng or _engine()
            samples, sr = eng.create(text, voice=voice, lang=LANGS[lang][0], speed=speed)
            _write_wav(p, samples, sr)
            made += 1
        man["scenes"][sc["id"]] = {"key": key, "path": str(p), "duration_s": round(wav_seconds(p), 3),
                                   "voice": voice, "speed": speed, "lang": lang, "text": text}
    man["synthesized"], man["cached"] = made, len(scenes) - made
    man["total_s"] = round(sum(x["duration_s"] for x in man["scenes"].values()), 3)
    (d / "manifest.json").write_text(json.dumps(man, indent=1))
    return {"status": "ok", "audio_dir": str(d), "lang": lang, "synthesized": made,
            "cached": man["cached"], "total_s": man["total_s"],
            "scenes": [{"id": sid, **v} for sid, v in man["scenes"].items()],
            "note": "" if scenes else "spec has no narration; nothing to synthesize"}
