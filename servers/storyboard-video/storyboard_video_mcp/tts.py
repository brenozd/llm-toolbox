"""Offline narration: Kokoro-82M (Apache-2.0) through kokoro-onnx, one WAV per narrated scene.

The model and voices are baked into the image (no runtime download). Synthesis is cached on
text+voice+speed+lang, so re-running narrate only pays for the lines that actually changed.
"""
from __future__ import annotations

import array
import hashlib
import json
import os
import random
import re
import wave
from pathlib import Path

from . import config, cues, spec as S

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
    _write_pcm(path, _pcm(samples), sr)


def _write_pcm(path: Path, pcm: bytes, sr: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm)


BEAT_S = 0.45  # a [beat] in the narration: a breath between two ideas
ROOM_PEAK = 20  # int16 peak of the room tone (~ -64 dBFS): never digital silence, far under the -38 dB pause detector


def room_tone(seconds: float, sr: int) -> bytes:
    """Deterministic low-level noise for a pause, so a pause does not sound like the audio dropping out."""
    rng = random.Random(7)
    return array.array("h", (rng.randint(-ROOM_PEAK, ROOM_PEAK) for _ in range(int(seconds * sr)))).tobytes()


def synthesize(eng, text: str, voice: str, lang: str, speed: float) -> tuple[bytes, int]:
    """One scene line -> PCM. `[beat]` splits the line: each part is synthesized on its own and the parts
    are joined by BEAT_S of room tone (the TTS never sees the marker, so it cannot read it out)."""
    parts = [x for x in S.BEAT.split(text) if x.strip()]
    pcm, sr = [], 24000
    for i, part in enumerate(parts):
        samples, sr = eng.create(part, voice=voice, lang=LANGS[lang][0], speed=speed)
        if i:
            pcm.append(room_tone(BEAT_S, sr))
        pcm.append(_pcm(samples))
    return b"".join(pcm), sr


def wav_seconds(path: Path) -> float:
    """Real duration from the file itself: the timeline must use what was spoken, not an estimate."""
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


def _voice_of(spec: dict, sc: dict) -> str:
    return sc.get("voice") or spec.get("voice") or LANGS[spec["lang"]][1]


def words_of(narration: str, wav: Path, say: dict | None) -> list[dict]:
    """Estimated word timings of the *written* narration (the one a cue names), weighted by how each
    word is spoken after spec.say."""
    clean = S.BEAT.sub(" ", re.sub(r"(\w)(\s*\[beat\])", r"\1,\2", narration, flags=re.I)).strip()  # a beat is a phrase boundary
    return cues.align(clean, wav, lambda w: pronounce(w, say))


def narrate(h: str, scratch: bool = False) -> dict:
    """Synthesize every narrated scene of spec `h` into /work/audio/<h>/, one WAV per scene, and
    write manifest.json with the measured durations that spec.timeline() then uses.

    `scratch=True` is the animatic pass: same Kokoro, same cache key, same WAVs -- the manifest is
    only *labelled* (`"scratch": true`) so a reader can tell the pass it came from. The
    label is metadata, not part of the cache key or of `resolved_hash`: narrating scratch first and
    final second reuses the same lines (that is the point) and the final id does not move."""
    spec = S.load(h)
    scenes = [sc for sc in spec["scenes"] if S._narration(sc)]
    lang = spec.get("lang")
    if lang not in LANGS:
        raise ValueError(f"spec.lang must be one of {sorted(LANGS)} to narrate (got {lang!r})")
    d = config.WORK / "audio" / h
    d.mkdir(parents=True, exist_ok=True)
    man = {"spec_hash": h, "lang": lang, "scratch": bool(scratch), "scenes": {}}
    eng, made = None, 0
    for sc in scenes:
        voice = _voice_of(spec, sc)
        speed = float(sc.get("speed") or spec.get("speed") or 1.0)
        text = pronounce(sc["narration"], spec.get("say"))
        key = cache_key(text + (f"\x00beat{BEAT_S}" if S.BEAT.search(text) else ""), voice, speed, lang)
        p = d / f"{sc['id']}-{key}.wav"  # scene id in the name: identical lines keep separate files
        if not p.exists():
            eng = eng or _engine()
            _write_pcm(p, *synthesize(eng, text, voice, lang, speed))
            made += 1
        man["scenes"][sc["id"]] = {"key": key, "path": str(p), "duration_s": round(wav_seconds(p), 3),
                                   "voice": voice, "speed": speed, "lang": lang, "text": text,
                                   "words": words_of(sc["narration"], p, spec.get("say")), "align": "estimated"}
    man["synthesized"], man["cached"] = made, len(scenes) - made
    man["total_s"] = round(sum(x["duration_s"] for x in man["scenes"].values()), 3)
    (d / "manifest.json").write_text(json.dumps(man, indent=1))
    return {"status": "ok", "audio_dir": str(d), "lang": lang, "synthesized": made,
            "cached": man["cached"], "total_s": man["total_s"], "scratch": bool(scratch),
            "scenes": [{"id": sid, **v} for sid, v in man["scenes"].items()],
            "note": "" if scenes else "spec has no narration; nothing to synthesize"}
