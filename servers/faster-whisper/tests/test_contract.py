"""Contract tests for the faster-whisper image: the two dependency pins and the model default.

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


def test_pins_keep_av_below_19() -> None:
    """av 19 removed the `metadata_errors` kwarg faster-whisper 1.2.1 passes."""
    deps = _deps()
    assert "<19" in deps["av"], deps["av"]
    assert deps["faster-whisper"].startswith(">=1.2.1,<1.3"), deps["faster-whisper"]
    assert _version("faster-whisper") < (1, 3), metadata.version("faster-whisper")
    assert 11 <= _version("av")[0] < 19, metadata.version("av")


def test_av_accepts_metadata_errors_kwarg() -> None:
    """The exact call that raised TypeError on av 19; any OSError is fine here."""
    import av

    try:
        av.open("/nonexistent/contract-test.wav", metadata_errors="ignore")
    except TypeError as exc:  # pragma: no cover - the av 19 regression
        raise AssertionError(f"av {av.__version__} rejects metadata_errors: {exc}") from exc
    except OSError:
        pass


def test_default_model_is_small_and_overridable() -> None:
    """tiny garbles pt-BR; small is the documented default, env still wins."""
    from faster_whisper_mcp.config import load_config

    saved = {k: os.environ.pop(k, None) for k in ("WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE")}
    try:
        assert load_config().model_size == "small"
        os.environ["WHISPER_MODEL"] = "tiny"
        assert load_config().model_size == "tiny"
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
