#!/usr/bin/env python3
"""Deterministic scope/authorization/budget guard for the security-review skill.

Stdlib only. Three entry points:
  verify_scope()      signed, unexpired scope manifest or raise ScopeError
  check_target()      exact scheme://host:port membership, no prefix/substring match
  run_with_budget()   run a command in its own process group under time/disk limits
                      (the disk budget is measured in --cwd, so cwd is required)

Every refusal is a ScopeError; the CLI turns it into exit 1 and runs nothing.
"""

import argparse
import ctypes
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# Namespace binds the signature to this manifest format, so a signature made for
# some other file type can't be replayed as a scope.
SIG_NAMESPACE = "security-review-scope"

REQUIRED_FIELDS = ("targets", "expiresAt", "maxSeconds", "maxDiskMB", "createdBy")

# Same shape as scope_schema.json's target pattern: a scheme is mandatory here, so a
# bare host:port (which would match any scheme) can never reach check_target().
TARGET_RE = re.compile(r"^[a-z][a-z0-9+.-]*://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?:[0-9]{1,5}$")

EXIT_TIMEOUT = 124
EXIT_DISK = 125

# Linux prctl(2): orphans reparent to us instead of init, so a descendant that
# escaped its process group is still visible as our child (see _kill_group).
PR_SET_CHILD_SUBREAPER = 36


class ScopeError(RuntimeError):
    """Scope missing, unsigned, badly signed, expired, or malformed."""


def _read_bytes(path: Path, what: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ScopeError(f"{what} unreadable: {path}: {exc}") from exc


def _load_scope(raw: bytes, scope_path) -> dict:
    """Parse the manifest from the exact bytes the signature was verified over."""
    path = Path(scope_path)
    try:
        scope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScopeError(f"scope manifest is not valid JSON: {path}: {exc}") from exc
    if not isinstance(scope, dict):
        raise ScopeError("scope manifest must be a JSON object")
    missing = [f for f in REQUIRED_FIELDS if f not in scope]
    if missing:
        raise ScopeError(f"scope manifest missing required fields: {', '.join(missing)}")
    unknown = sorted(set(scope) - set(REQUIRED_FIELDS))
    if unknown:
        # scope_schema.json is additionalProperties: false; an ignored field would be
        # silently unenforced authorization.
        raise ScopeError(f"scope manifest has unknown fields: {', '.join(unknown)}")
    if not isinstance(scope["targets"], list) or not scope["targets"]:
        raise ScopeError("scope manifest 'targets' must be a non-empty list")
    seen: set[str] = set()
    for target in scope["targets"]:
        # The regex is the schema's rule; _parse_endpoint still rejects e.g. port 99999.
        if (not isinstance(target, str) or TARGET_RE.match(target) is None
                or _parse_endpoint(target) is None):
            raise ScopeError("invalid target: expected exact scheme://host:port")
        if target in seen:  # schema's uniqueItems: true
            raise ScopeError("scope manifest 'targets' contains a duplicate entry")
        seen.add(target)
    for field in ("maxSeconds", "maxDiskMB"):
        value = scope[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ScopeError(f"scope manifest '{field}' must be a positive integer")
    if not isinstance(scope["createdBy"], str) or not scope["createdBy"].strip():
        raise ScopeError("scope manifest 'createdBy' must be a non-empty string")
    _parse_expiry(scope["expiresAt"])  # the schema's format rule, applied at load time
    return scope


# scope_schema.json's expiresAt pattern: the offset needs a ':' ("+00:00"), because
# datetime.fromisoformat alone also accepts the ambiguous compact "+0000".
EXPIRES_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


def _parse_expiry(value) -> datetime:
    if not isinstance(value, str):
        raise ScopeError("scope manifest 'expiresAt' must be an ISO 8601 string")
    if EXPIRES_RE.match(value) is None:
        raise ScopeError("scope manifest 'expiresAt' must be an ISO 8601 instant with a "
                         "timezone offset written as Z or +HH:MM")
    try:
        expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScopeError("scope manifest 'expiresAt' is not a valid ISO 8601 instant") from exc
    if expires.tzinfo is None:
        raise ScopeError("scope manifest 'expiresAt' must carry a timezone offset")
    return expires


def _parse_endpoint(raw: str):
    """(scheme, host, port) for an exact endpoint, or None if it isn't one.

    scheme is None for a bare host:port; callers reject that rather than let it
    match any scheme.
    """
    raw = raw.strip()
    if "://" in raw:
        parts = urlsplit(raw)
        if not parts.scheme:
            return None
        scheme, host = parts.scheme.lower(), parts.hostname
        try:
            port = parts.port
        except ValueError:
            return None
    else:
        scheme = None
        host, _, port_text = raw.rpartition(":")
        port = int(port_text) if port_text.isdigit() else None
    if not host or port is None:
        return None  # the port is always explicit: no default-port guessing
    host = host.lower().rstrip(".")
    if not host or any(c in host for c in "*?,["):
        return None  # no wildcards, no lists
    return scheme, host, port


def check_target(scope: dict, url_or_host_port: str) -> bool:
    """True only if the target is one of the scope's exact scheme://host:port entries."""
    if not isinstance(scope, dict) or not isinstance(url_or_host_port, str):
        return False
    wanted = _parse_endpoint(url_or_host_port)
    if wanted is None or wanted[0] is None:
        return False  # a bare host:port would match any scheme: no scheme, no match
    for target in scope.get("targets") or []:
        if not isinstance(target, str):
            continue
        if _parse_endpoint(target) == wanted:
            return True
    return False


def _allowed_signers(pubkey_bytes: bytes, pubkey_path: Path, tmpdir: Path) -> Path:
    """One-key allowed_signers file, built in a temp dir (never inside the workspace)."""
    fields = pubkey_bytes.decode("utf-8", "replace").split()
    if len(fields) < 2:
        raise ScopeError(f"public key file is not an SSH public key: {pubkey_path}")
    signers = tmpdir / "allowed_signers"
    # `*` principals = this single key may sign for any identity; the key is the whole trust anchor.
    signers.write_text(f'* namespaces="{SIG_NAMESPACE}" {" ".join(fields[:2])}\n')
    return signers


def _verify_signature(raw_scope: bytes, sig_path: Path, signers: Path) -> None:
    """Verify `raw_scope` itself (fed on stdin), so what is verified is what gets parsed."""
    proc = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", "scope-signer",
         "-n", SIG_NAMESPACE, "-s", str(sig_path)],
        input=raw_scope,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode(errors="replace").strip()
        raise ScopeError(f"scope signature verification failed: {detail}")


def verify_scope(scope_path, sig_path, pubkey_path) -> dict:
    """Load the scope and prove it was signed by `pubkey_path` and hasn't expired.

    `pubkey_path` is always explicit: the caller passes the user's key (e.g. under
    ~/.ssh). Nothing is discovered inside the repo, and a key sitting next to the
    manifest is refused, because whoever plants the manifest could plant the key.
    """
    scope_path = Path(scope_path)
    sig_path = Path(sig_path)
    pubkey_path = Path(pubkey_path)
    if not scope_path.is_file():
        raise ScopeError(f"scope manifest not found: {scope_path}")
    if not sig_path.is_file():
        raise ScopeError(f"scope signature not found: {sig_path} (unsigned scope)")
    if not pubkey_path.is_file():
        raise ScopeError(f"public key not found: {pubkey_path}")

    workspace = scope_path.resolve().parent
    # Resolve the key once and use that single path for the workspace check and for
    # the read, so a symlink swap can't get one file approved and another read.
    pubkey_real = pubkey_path.resolve()
    if workspace in pubkey_real.parents:
        raise ScopeError(
            f"public key {pubkey_path} lives inside the workspace {workspace}; "
            "pass the user's key from outside the workspace"
        )

    # Read both files exactly once. The signature is verified over these bytes and
    # the manifest is parsed from these same bytes: no re-read for an attacker to
    # race between the check and the use.
    pubkey_bytes = _read_bytes(pubkey_real, "public key")
    raw_scope = _read_bytes(scope_path, "scope manifest")

    with tempfile.TemporaryDirectory(prefix="scope-verify-") as tmp:
        signers = _allowed_signers(pubkey_bytes, pubkey_real, Path(tmp))
        _verify_signature(raw_scope, sig_path, signers)

    scope = _load_scope(raw_scope, scope_path)
    expires = _parse_expiry(scope["expiresAt"])
    if expires <= datetime.now(timezone.utc):
        raise ScopeError("scope manifest has expired")
    return scope


def _disk_mb(root: Path) -> float:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        for name in filenames:
            try:
                total += os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total / (1024 * 1024)


def _signal(pid: int, sig) -> None:
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _descendants(*roots: int) -> list[int]:
    """PIDs whose ancestry leads to one of `roots`, read from /proc (Linux only)."""
    children: dict[int, list[int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return []
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8", errors="replace") as fh:
                stat = fh.read()
        except OSError:
            continue
        # comm may contain spaces and parens: the fields after the last ')' are
        # state, ppid, ...
        fields = stat.rsplit(")", 1)[-1].split()
        if len(fields) < 2:
            continue
        children.setdefault(int(fields[1]), []).append(int(entry))
    found: list[int] = []
    stack = list(roots)
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.append(child)
                stack.append(child)
    return found


def _become_subreaper() -> bool:
    """Linux: make orphaned descendants reparent to us rather than to init."""
    try:
        return ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def _reap_known(pids: list[int], deadline_s: float = 1.0) -> None:
    """Reap only pids we already know are ours, so they don't linger as zombies.

    Never waitpid(-1): as a library the guard shares the process with its caller, and
    reaping the caller's children throws away their real exit status (a foreign exit
    42 then reads back as 0).
    """
    deadline = time.monotonic() + deadline_s
    for pid in pids:
        while True:
            try:
                reaped, _status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break  # not our child, or already reaped by poll()/wait()
            if reaped or time.monotonic() >= deadline:
                break
            time.sleep(0.01)


def _kill_group(proc: subprocess.Popen, pgid: int, preexisting=frozenset(),
                grace: float = 2.0) -> None:
    """SIGTERM then SIGKILL the child, its process group, and escaped descendants.

    Used on the timeout path and after a normal exit, so a background grandchild
    never outlives the guard.

    shortcut: a descendant that calls setsid() leaves the process group, so killpg
    alone would miss it. Covered by becoming PR_SET_CHILD_SUBREAPER and killing
    every /proc descendant before the parent is reaped; not covered if prctl or
    /proc is unavailable (non-Linux, seccomp), and not a pid-namespace boundary.
    Upgrade to running the command under a cgroup (or the bucket-2 container) if
    the command is untrusted rather than merely audited.

    `preexisting` are the caller's own children (as a library, we share the process
    with it): never signalled and never reaped.
    """
    known: list[int] = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if proc.returncode is None:
            # killpg only while the group leader is still unreaped: once it is gone its
            # pgid may already belong to an unrelated process, and killpg would hit it.
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        # Rescan before reaping: a descendant forked by a signal handler only shows up
        # here. /proc links are live, so a recycled pid is never named; the caller's own
        # children (preexisting) are left alone.
        for pid in _descendants(os.getpid()):
            if pid not in preexisting and pid not in known:
                known.append(pid)
        for pid in known:
            _signal(pid, sig)
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            continue
        # The direct child is gone; leftovers may have survived SIGTERM, so SIGKILL next.
    _reap_known(known)


def run_with_budget(cmd: list[str], max_seconds: int, max_disk_mb: int | None,
                    cwd=None) -> int:
    """Run `cmd` in a new session under wall-clock (and optional disk) limits.

    Returns the command's exit code, EXIT_TIMEOUT when killed for time, or
    EXIT_DISK when killed for disk. The whole process group is killed, not just
    the direct child.
    """
    if max_disk_mb is not None and cwd is None:
        raise ValueError("a disk budget needs cwd: nowhere else to measure it")
    if not _become_subreaper():
        # Escaped setsid() descendants can then survive; say so instead of pretending.
        print("guard: warning: cannot become child subreaper (prctl failed); "
              "descendants that escape the process group may survive", file=sys.stderr)
    # Snapshot the caller's children *before* forking: taken after Popen, the command's
    # own early descendants (e.g. one that setsid()s at once) would be in the snapshot
    # and protected from the kill sweep.
    # shortcut: the caller's children that already exist now are protected; one it
    # forks during our run is not distinguishable from an escaped descendant.
    preexisting = frozenset(_descendants(os.getpid()))
    # stdin is /dev/null: the command can never block on the caller's terminal.
    # Real isolation of a command that leaks stdout/stderr holders is the bucket-2
    # container; here it is only guaranteed that the guard itself returns.
    proc = subprocess.Popen(cmd, cwd=cwd, start_new_session=True,
                            stdin=subprocess.DEVNULL)
    pgid = proc.pid  # start_new_session=True: recorded before any reap, so it can't be recycled
    started = time.monotonic()
    # shortcut: the disk budget is sampled once per second, so a write-then-delete
    # under the budget inside that window is invisible; upgrade to inotify/fanotify
    # or a cgroup space limit if the command is adversarial rather than audited.
    next_disk_check = started + 1.0
    while True:
        code = proc.poll()
        if code is not None:
            _kill_group(proc, pgid, preexisting)  # a background grandchild must not outlive a clean exit
            return code
        now = time.monotonic()
        if now - started >= max_seconds:
            _kill_group(proc, pgid, preexisting)
            return EXIT_TIMEOUT
        if max_disk_mb is not None and now >= next_disk_check:
            next_disk_check = now + 1.0
            if _disk_mb(Path(cwd)) > max_disk_mb:
                _kill_group(proc, pgid, preexisting)
                return EXIT_DISK
        time.sleep(0.05)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="security-review scope guard")
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="verify the scope, then run a command under budget")
    run.add_argument("--scope", required=True)
    run.add_argument("--sig", required=True)
    run.add_argument("--pubkey", required=True)
    run.add_argument("--max-seconds", type=int, required=True)
    run.add_argument("--max-disk-mb", type=int, default=None)
    run.add_argument("--cwd", default=None,
                     help="working directory; required, the disk budget is measured in it")
    run.add_argument("--target", required=True,
                     help="exact scheme://host:port the command will test")
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        parser.error("no command given after --")
    if args.max_seconds < 1 or (args.max_disk_mb is not None and args.max_disk_mb < 1):
        parser.error("budgets must be positive integers")
    if args.cwd is None:
        # The signed maxDiskMB is always the default budget, and it is measured in cwd:
        # without one the budget would be silently unenforceable.
        parser.error("--cwd is required: the disk budget (maxDiskMB, or --max-disk-mb) "
                     "is measured in it")

    try:
        scope = verify_scope(args.scope, args.sig, args.pubkey)
    except ScopeError as exc:
        print(f"guard: {exc}", file=sys.stderr)
        return 1

    if "://" not in args.target:
        parser.error("--target must be an exact scheme://host:port; a bare host:port "
                     "would match any scheme")
    if not check_target(scope, args.target):
        print(f"guard: target {args.target!r} is not in the signed scope", file=sys.stderr)
        return 1

    # The manifest's budgets are the ceiling; the CLI may only tighten them.
    max_seconds = min(args.max_seconds, scope["maxSeconds"])
    max_disk_mb = (scope["maxDiskMB"] if args.max_disk_mb is None
                   else min(args.max_disk_mb, scope["maxDiskMB"]))
    try:
        return run_with_budget(cmd, max_seconds, max_disk_mb, cwd=args.cwd)
    except OSError as exc:
        print(f"guard: cannot run {cmd[0]!r}: {exc}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(main())
