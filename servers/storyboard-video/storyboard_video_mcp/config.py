from __future__ import annotations

import os
from pathlib import Path

WORK = Path(os.environ.get("STORYBOARD_WORK", "/work"))
REPO = Path(os.environ.get("STORYBOARD_REPO", "/repo"))
# Read-only music cache the music-search skill stages tracks into (mounted at /music by plugin.json).
# STORYBOARD_MUSIC_DIR mounts the same cache elsewhere (a host that keeps its music outside ~/.cache):
# a wrong value degrades to `music_path_missing` on the spec, never to reading some other path.
MUSIC_DIR = Path(os.environ.get("STORYBOARD_MUSIC_DIR", "/music"))
SFX_DIR = Path(os.environ.get("STORYBOARD_SFX_DIR", "/sfx"))  # staged library effects (music-search --kind sfx)
# Set by the operator in `docker run`, never by the model: gates every tool that runs repo code.
ALLOW_EXEC = os.environ.get("STORYBOARD_ALLOW_EXEC") == "1"
WEB_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal"}
MUSIC_VOLUME_DB = (-40.0, 0.0)  # a music bed under narration: never louder than the voice
MUSIC_DUCK_DB = (0.0, 40.0)
# Bumped whenever the template or the timeline changes what a render looks like: it is part of
# spec.resolved_hash, so old stills/receipts cannot be reused for a frame built by another template.
RENDER_VERSION = "5"
AUDIO_VERSION = "2"  # bump when the mix chain changes (v2: -14 LUFS default + limiter): old cached mixes must not be reused
# Pocket TTS binary (baked into the image). Its name + size is part of the narration cache key: a re-baked
# engine must not be served the WAVs the previous one synthesized. TTS_HOME is the HF cache with the baked weights.
MODEL = Path(os.environ.get("STORYBOARD_TTS_BIN", "/opt/pocket-tts/pocket-tts"))
TTS_HOME = os.environ.get("STORYBOARD_TTS_HOME", "/opt/hf")


def model_id() -> str:
    """Stable identity of the baked TTS binary, cheap enough to hash on every call."""
    try:
        return f"{MODEL.name}:{MODEL.stat().st_size}"
    except OSError:
        return f"{MODEL.name}:absent"


def tts_env() -> dict[str, str]:
    """Offline by construction: the weights come from the image, a missing one must fail, not download."""
    return {**os.environ, "HF_HOME": TTS_HOME, "HF_HUB_OFFLINE": "1"}


def chromium() -> str | None:
    """Explicit path, else Playwright's own (None => let Playwright resolve)."""
    return os.environ.get("STORYBOARD_CHROMIUM") or None
