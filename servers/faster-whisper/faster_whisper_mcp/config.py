from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    model_size: str
    device: str
    compute_type: str


def load_config() -> Config:
    return Config(
        model_size=os.environ.get("WHISPER_MODEL", "tiny"),
        device=os.environ.get("WHISPER_DEVICE", "cpu"),
        compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
    )
