from __future__ import annotations

import os
from pathlib import Path

WORK = Path(os.environ.get("PROMO_WORK", "/work"))
REPO = Path(os.environ.get("PROMO_REPO", "/repo"))
# Bundled CC0/PD soundtrack (music/catalog.json next to the package), read-only, baked into the image.
MUSIC = Path(os.environ.get("PROMO_MUSIC") or Path(__file__).resolve().parent.parent / "music")
# Set by the operator in `docker run`, never by the model: gates every tool that runs repo code.
ALLOW_EXEC = os.environ.get("PROMO_ALLOW_EXEC") == "1"
WEB_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal"}
MUSIC_VOLUME_DB = (-40.0, 0.0)  # a music bed under narration: never louder than the voice
MUSIC_DUCK_DB = (0.0, 40.0)
# Bumped whenever the template or the timeline changes what a render looks like: it is part of
# spec.resolved_hash, so old stills/receipts cannot be reused for a frame built by another template.
RENDER_VERSION = "2"
# TTS model identity (name + size, not a 300 MB hash) is part of the narration cache key: a re-baked
# model must not be served the WAVs the previous one synthesized.
MODEL = Path(os.environ.get("PROMO_KOKORO_MODEL", "/opt/kokoro/kokoro-v1.0.fp16.onnx"))


def model_id() -> str:
    """Stable identity of the baked TTS model, cheap enough to hash on every call."""
    try:
        return f"{MODEL.name}:{MODEL.stat().st_size}"
    except OSError:
        return f"{MODEL.name}:absent"


def chromium() -> str | None:
    """Explicit path, else Playwright's own (None => let Playwright resolve)."""
    return os.environ.get("PROMO_CHROMIUM") or None
