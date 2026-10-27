"""Downloaded-media path handling: sanitized names, no traversal, no overwrite, no symlinks."""
from __future__ import annotations

import os
import re
from pathlib import Path

NAME_MAX = 255
_FALLBACK = "file"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_name(name: str | None, fallback: str = _FALLBACK) -> str:
    """Basename-safe name: no control chars, separators, leading dots; never "" or "." / ".."."""
    cleaned = _UNSAFE.sub("_", (name or "").replace("\x00", "")).strip("._-")
    cleaned = cleaned.lstrip(".")
    if not cleaned or cleaned.strip(".") == "":
        cleaned = fallback
    return cleaned


def _clip(name: str, limit: int) -> str:
    """Fit a name into `limit` bytes without splitting an extension."""
    stem, dot, ext = name.rpartition(".")
    if dot and 1 < len(ext) <= 16:
        room = limit - len(ext) - 1
        return f"{stem[:max(room, 1)]}.{ext}" if room > 0 else name[:limit]
    return name[:limit]


def download_name(message_id: str, filename: str | None) -> str:
    """`<message-id>-<sanitized name>`, safe for NAME_MAX even with a uniqueness suffix."""
    return _clip(f"{sanitize_name(message_id, 'message')}-{sanitize_name(filename)}", NAME_MAX - 8)


def downloads_dir(data_dir: str | Path) -> Path:
    """The (created, 0700) downloads dir; refuses to follow a symlink planted there."""
    d = Path(data_dir) / "downloads"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    if d.is_symlink() or not d.is_dir():
        raise RuntimeError("downloads dir is not a directory")
    return d


def write_download(data_dir: str | Path, message_id: str, filename: str | None, data: bytes) -> Path:
    """Write bytes to `<data_dir>/downloads/<unique name>` with O_EXCL|O_NOFOLLOW, 0600. Never overwrites."""
    directory = downloads_dir(data_dir)
    base = download_name(message_id, filename)
    for attempt in range(100):
        candidate = directory / (base if attempt == 0 else f"{base}-{attempt}")
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except BaseException:
            candidate.unlink(missing_ok=True)
            raise
        return candidate
    raise RuntimeError("could not find a free file name for the download")
