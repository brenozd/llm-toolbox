from __future__ import annotations

import av
import numpy as np

SAMPLE_RATE = 16000
# Fixed windows: a 640 s buffer crashed the native engine (segfault), 160 s decoded fine.
CHUNK_S = 60


def load_audio(path: str) -> np.ndarray:
    """Decode any container PyAV reads (ogg/opus, m4a, mp3, wav...) to 16 kHz mono float32."""
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    parts = []
    with av.open(path, metadata_errors="ignore") as container:
        for frame in container.decode(audio=0):
            parts.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(frame))
    return np.concatenate(parts) if parts else np.zeros(0, np.float32)


def transcribe(session, audio_path: str, language: str | None = None, output_format: str = "json") -> object:
    """Transcribe an audio file in 60 s windows. output_format: json (segments) or text."""
    if output_format not in ("json", "text"):
        raise ValueError("output_format must be json or text")
    pcm = load_audio(audio_path)
    step = CHUNK_S * SAMPLE_RATE
    segments = []
    for off in range(0, len(pcm), step):
        text = session.run(np.ascontiguousarray(pcm[off:off + step]), language=language, timestamps="none").text.strip()
        if text:
            segments.append({"start": off / SAMPLE_RATE, "end": min(off + step, len(pcm)) / SAMPLE_RATE, "text": text})
    text = " ".join(s["text"] for s in segments)
    if output_format == "text":
        return text
    return {"duration": len(pcm) / SAMPLE_RATE, "text": text, "segments": segments}
