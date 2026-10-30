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
        # small, not tiny: tiny garbles pt-BR (WER 0.40 vs 0.00 on short accented lines).
        model_size=os.environ.get("WHISPER_MODEL", "small"),
        device=os.environ.get("WHISPER_DEVICE", "cpu"),
        compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
    )
