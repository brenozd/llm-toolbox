from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    repo: str
    filename: str


def load_config() -> Config:
    # Parakeet-TDT 0.6B v3 (multilingual, pt-BR): WER 0.055 on 80 FLEURS/Common Voice clips at ~16x
    # real time on CPU, vs 0.049 and 1.1x for whisper large-v3-turbo. Any GGUF repo supported by
    # transcribe-cpp works here.
    return Config(
        repo=os.environ.get("ASR_MODEL_REPO", "handy-computer/parakeet-tdt-0.6b-v3-gguf"),
        filename=os.environ.get("ASR_MODEL_FILE", "parakeet-tdt-0.6b-v3-Q8_0.gguf"),
    )
