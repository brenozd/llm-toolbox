from __future__ import annotations

import fnmatch
from pathlib import Path

from . import config

DENY = [".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "id_ecdsa*", ".npmrc", ".pypirc",
        "credentials*", ".netrc", "*.p12", "*.pfx", "secrets.*", ".git-credentials"]
DENY_DIRS = {".git", ".ssh", ".aws", ".gnupg"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "build", "dist", "target", "__pycache__", ".cache",
             ".next", ".tox", "vendor", ".gradle", ".idea", "_deps"}


def denied(p: Path) -> bool:
    if any(part in DENY_DIRS for part in p.parts):
        return True
    n = p.name
    if n in (".env.example", ".env.sample", ".env.template"):
        return False  # names only are read by scan_repo, never values
    return any(fnmatch.fnmatch(n, pat) for pat in DENY)


def safe_path(p: str | Path, roots: list[Path] | None = None) -> Path:
    """Resolve p and require it to sit under an allowed root and not be a secret file."""
    roots = roots or [config.REPO, config.WORK]
    rp = Path(p).expanduser().resolve()
    if not any(rp == r.resolve() or r.resolve() in rp.parents for r in roots):
        raise PermissionError(f"path outside allowed roots: {p}")
    if denied(rp):
        raise PermissionError(f"refusing secret-looking path: {rp.name}")
    return rp
