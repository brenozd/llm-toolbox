"""Contract tests for the transcription image: the engine pin and the model default.

Plain asserts (no fixtures), so they run both under pytest and with a bare
``python3 -c "[getattr(tc, n)() for n in dir(tc) if n.startswith('test_')]"`` inside the
distroless runtime image, which has no Python tooling of its own.
"""

from __future__ import annotations

import os
import re
import tomllib
from importlib import metadata
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _deps() -> dict[str, str]:
    data = tomllib.loads(PYPROJECT.read_text())
    out = {}
    for spec in data["project"]["dependencies"]:
        name, version = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", spec).groups()
        out[name.lower()] = version
    return out


def _version(pkg: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", metadata.version(pkg))[:3])


def test_native_engine_is_pinned() -> None:
    """transcribe-cpp is 0.x: its API may break between releases."""
    assert _deps()["transcribe-cpp"].startswith("==0.2."), _deps()["transcribe-cpp"]
    assert _version("transcribe-cpp")[:2] == (0, 2), metadata.version("transcribe-cpp")


def test_default_model_is_parakeet_v3_and_overridable() -> None:
    from audio_transcribe_mcp.config import load_config

    saved = os.environ.pop("ASR_MODEL_FILE", None)
    try:
        assert "parakeet-tdt-0.6b-v3" in load_config().filename
        os.environ["ASR_MODEL_FILE"] = "x.gguf"
        assert load_config().filename == "x.gguf"
    finally:
        os.environ.pop("ASR_MODEL_FILE", None)
        if saved is not None:
            os.environ["ASR_MODEL_FILE"] = saved
