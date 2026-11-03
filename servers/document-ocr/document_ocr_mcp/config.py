from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    roots: tuple[Path, ...]
    max_bytes: int
    max_pages: int
    timeout_s: int
    dpi: int
    workers: int


def load_config() -> Config:
    roots = os.environ.get("DOCUMENT_OCR_ROOTS", "/data")
    return Config(
        roots=tuple(Path(r).resolve() for r in roots.split(":") if r),
        max_bytes=int(os.environ.get("DOCUMENT_OCR_MAX_MB", "50")) * 1024 * 1024,
        max_pages=int(os.environ.get("DOCUMENT_OCR_MAX_PAGES", "20")),
        timeout_s=int(os.environ.get("DOCUMENT_OCR_TIMEOUT_S", "60")),
        # 200 dpi puts A4 body text near the ~30 px cap-height Tesseract likes; measured value pending.
        dpi=int(os.environ.get("DOCUMENT_OCR_DPI", "200")),
        workers=int(os.environ.get("DOCUMENT_OCR_WORKERS", str(os.cpu_count() or 1))),
    )
