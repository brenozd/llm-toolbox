from __future__ import annotations

import subprocess
from pathlib import Path


def convert_to_opus_ogg(src: Path, dst: Path) -> None:
    """Voice-note encode via ffmpeg (argv list, no shell). dst must live outside the media dir."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-vn", "-c:a", "libopus", "-b:a", "32k",
           "-ar", "24000", "-application", "voip", "-y", str(dst)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg is not installed") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("audio conversion timed out") from None
    except subprocess.CalledProcessError:
        raise RuntimeError("audio conversion failed") from None
