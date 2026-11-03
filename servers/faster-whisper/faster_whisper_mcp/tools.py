from __future__ import annotations

from faster_whisper import WhisperModel

# Whisper's known silence hallucinations (YouTube-subtitle artifacts), dropped from the output.
_HALLUCINATIONS = ("amara.org", "legendas pela comunidade", "obrigado por assistir", "inscreva-se")


def transcribe(model: WhisperModel, audio_path: str, language: str | None = None,
               initial_prompt: str | None = None, output_format: str = "json") -> object:
    """Transcribe an audio file; VAD skips silence. output_format: json (segments) or text."""
    if output_format not in ("json", "text"):
        raise ValueError("output_format must be json or text")
    segments, info = model.transcribe(
        audio_path, language=language, initial_prompt=initial_prompt,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        # a bad segment must not seed the next one (the loop behind repeated phrases)
        condition_on_previous_text=False, no_speech_threshold=0.6, log_prob_threshold=-1.0,
    )
    segments = [
        {"start": s.start, "end": s.end, "text": s.text.strip()}
        for s in segments
        if not any(h in s.text.lower() for h in _HALLUCINATIONS)
    ]
    text = " ".join(s["text"] for s in segments)
    if output_format == "text":
        return text
    return {"language": info.language, "text": text, "segments": segments}
