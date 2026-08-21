from __future__ import annotations

from faster_whisper import WhisperModel


def transcribe(model: WhisperModel, audio_path: str, language: str | None = None) -> object:
    """Transcribe an audio file, returning full text and per-segment timestamps."""
    segments, info = model.transcribe(audio_path, language=language)
    segments = [
        {"start": s.start, "end": s.end, "text": s.text.strip()}
        for s in segments
    ]
    return {
        "language": info.language,
        "text": " ".join(s["text"] for s in segments),
        "segments": segments,
    }
