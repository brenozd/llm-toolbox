"""Real (no mocks) tests for guard.py: ssh-keygen signatures, exit codes, process groups."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import guard  # noqa: E402

GUARD = str(Path(__file__).parent / "guard.py")
NAMESPACE = guard.SIG_NAMESPACE


def make_keypair(tmp_path: Path, name: str = "id_test") -> Path:
    key = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name,
                    "-f", str(key)], check=True)
    return key


def make_scope(expires_at: str = "2999-01-01T00:00:00Z") -> dict:
    return {
        "targets": ["https://example.com:443", "http://127.0.0.1:8080"],
        "expiresAt": expires_at,
        "maxSeconds": 60,
        "maxDiskMB": 10,
        "createdBy": "tester@example.com",
    }


@pytest.fixture
def workspace(tmp_path):
    """The reviewed workspace: holds the manifest, never the key."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def signed(tmp_path, workspace):
    key = make_keypair(tmp_path)  # key lives outside the workspace, like ~/.ssh
    scope_path = workspace / "scope.json"
    scope_path.write_text(json.dumps(make_scope()))
    subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", NAMESPACE,
                    str(scope_path)], check=True, cwd=workspace)
    return {
        "key": key,
        "pubkey": Path(str(key) + ".pub"),
        "scope": scope_path,
        "sig": Path(str(scope_path) + ".sig"),
    }


_AUTO = object()  # sentinel: run_cli's default cwd (the workspace)


def run_cli(files, extra=(), max_seconds=5, target="http://127.0.0.1:8080",
            cwd=_AUTO):
    extra = list(extra)
    cwd_args = []
    if "--cwd" not in extra:
        work = files["scope"].parent if cwd is _AUTO else cwd
        if work is not None:  # cwd=None: leave it out, to test the missing-cwd error
            cwd_args = ["--cwd", str(work)]
    cmd = [sys.executable, GUARD, "run",
           "--scope", str(files["scope"]), "--sig", str(files["sig"]),
           "--pubkey", str(files.get("pubkey", files["key"])),
           "--target", target,
           "--max-seconds", str(max_seconds), *cwd_args, *extra]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def wait_dead(pid: int, deadline_s: float = 2.5) -> None:
    """Assert the process is gone (and not a zombie) before the deadline."""
    deadline = time.monotonic() + deadline_s
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        assert time.monotonic() < deadline, f"pid {pid} still alive"
        time.sleep(0.05)


# --- signature path -------------------------------------------------------

def test_valid_signature_verifies(signed):
    scope = guard.verify_scope(signed["scope"], signed["sig"], signed["pubkey"])
    assert scope["createdBy"] == "tester@example.com"
    assert run_cli(signed, ["--", "true"]).returncode == 0


def test_unsigned_scope_exits_nonzero(tmp_path, workspace, signed):
    sig = workspace / "missing.sig"
    assert not sig.exists()
    files = {**signed, "sig": sig}
    proc = run_cli(files, ["--", "true"])
    assert proc.returncode != 0
    assert "signature not found" in proc.stderr


def test_tampered_signature_exits_nonzero(workspace, signed):
    sig = signed["sig"].read_bytes()
    body = sig.index(b"-----BEGIN SSH SIGNATURE-----") + 30
    flip = b"A" if sig[body:body + 1] != b"A" else b"B"
    signed["sig"].write_bytes(sig[:body] + flip + sig[body + 1:])
    proc = run_cli(signed, ["--", "true"])
    assert proc.returncode != 0
    assert "signature verification failed" in proc.stderr


def test_tampered_manifest_exits_nonzero(signed):
    scope = json.loads(signed["scope"].read_text())
    scope["targets"].append("https://evil.example.net:443")
    signed["scope"].write_text(json.dumps(scope))
    proc = run_cli(signed, ["--", "true"])
    assert proc.returncode != 0
    assert "signature verification failed" in proc.stderr


def test_expired_scope_exits_nonzero(signed):
    signed["scope"].write_text(json.dumps(make_scope("2000-01-01T00:00:00Z")))
    signed["sig"].unlink()  # re-sign the new content; ssh-keygen won't overwrite
    subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(signed["key"]),
                    "-n", NAMESPACE, str(signed["scope"])],
                   check=True, cwd=signed["scope"].parent)
    proc = run_cli(signed, ["--", "true"])
    assert proc.returncode != 0
    assert "expired" in proc.stderr


def test_pubkey_inside_workspace_is_refused(tmp_path, workspace, signed):
    smuggled = workspace / "attacker.pub"
    smuggled.write_bytes(signed["pubkey"].read_bytes())
    proc = run_cli({**signed, "pubkey": smuggled}, ["--", "true"])
    assert proc.returncode != 0
    assert "inside the workspace" in proc.stderr


def test_pubkey_symlink_into_workspace_is_refused(tmp_path, workspace, signed):
    # Resolution happens once, so the workspace check and the read see the same file.
    smuggled = workspace / "attacker.pub"
    smuggled.write_bytes(signed["pubkey"].read_bytes())
    link = tmp_path / "outside.pub"
    link.symlink_to(smuggled)
    proc = run_cli({**signed, "pubkey": link}, ["--", "true"])
    assert proc.returncode != 0
    assert "inside the workspace" in proc.stderr


def test_pubkey_symlink_outside_workspace_works(tmp_path, signed):
    link = tmp_path / "key-link.pub"
    link.symlink_to(signed["pubkey"])
    scope = guard.verify_scope(signed["scope"], signed["sig"], link)
    assert scope["maxSeconds"] == 60


def test_manifest_swap_after_verify_cannot_change_scope(signed, monkeypatch):
    """TOCTOU proof: the parsed dict comes from the bytes that were verified."""
    real_verify = guard._verify_signature

    def verify_then_swap(*args, **kwargs):
        real_verify(*args, **kwargs)
        # Attacker replaces the manifest right after ssh-keygen read it.
        signed["scope"].write_text(json.dumps({**make_scope(), "maxSeconds": 999999}))

    monkeypatch.setattr(guard, "_verify_signature", verify_then_swap)
    scope = guard.verify_scope(signed["scope"], signed["sig"], signed["pubkey"])
    assert scope["maxSeconds"] == 60
    assert json.loads(signed["scope"].read_text())["maxSeconds"] == 999999


# --- target binding -------------------------------------------------------

def test_out_of_scope_target_runs_nothing(signed, tmp_path):
    sentinel = tmp_path / "sentinel"
    proc = run_cli(signed, ["--", "touch", str(sentinel)],
                   target="https://evil.example.net:443")
    assert proc.returncode == 1
    assert "not in the signed scope" in proc.stderr
    assert not sentinel.exists()


def test_in_scope_target_runs(signed, tmp_path):
    sentinel = tmp_path / "sentinel"
    proc = run_cli(signed, ["--", "touch", str(sentinel)])
    assert proc.returncode == 0, proc.stderr
    assert sentinel.exists()


# --- target matching ------------------------------------------------------

def test_check_target_exact_match():
    scope = make_scope()
    assert guard.check_target(scope, "https://example.com:443")
    assert guard.check_target(scope, "http://127.0.0.1:8080")
    assert guard.check_target(scope, "https://example.com:443/admin?x=1")
    # A bare host:port carries no scheme, so it must not inherit one from the scope.
    assert guard.check_target(scope, "127.0.0.1:8080") is False
    assert guard.check_target(scope, "example.com:443") is False


@pytest.mark.parametrize("probe", [
    "https://evil-example.com:443",   # substring/suffix of example.com
    "https://example.com.evil.net:443",
    "https://example.com:8443",       # different port
    "http://example.com:443",         # different scheme
    "https://other.example.com:443",
    "https://example.com",
    "https://*.example.com:443",
    "127.0.0.1:8080",                # bare host:port: no scheme, no match
])
def test_check_target_rejects(probe):
    assert guard.check_target(make_scope(), probe) is False


def test_scheme_less_target_is_rejected(tmp_path):
    """scope_schema.json forbids bare host:port; the loader must enforce it too."""
    scope = {**make_scope(), "targets": ["example.com:443"]}
    with pytest.raises(guard.ScopeError, match="invalid target"):
        guard._load_scope(json.dumps(scope).encode(), tmp_path / "scope.json")
    scope = {**make_scope(), "targets": ["https://example.com"]}  # no port either
    with pytest.raises(guard.ScopeError, match="invalid target"):
        guard._load_scope(json.dumps(scope).encode(), tmp_path / "scope.json")


def test_scheme_less_cli_target_is_refused(signed, tmp_path):
    sentinel = tmp_path / "sentinel"
    proc = run_cli(signed, ["--", "touch", str(sentinel)], target="127.0.0.1:8080")
    assert proc.returncode != 0
    assert "scheme" in proc.stderr
    assert not sentinel.exists()


# --- schema rules enforced at load time -----------------------------------

def test_static_artifact_targets_are_endpoints_too(tmp_path):
    """Static reviews (Dockerfile, compose, k8s YAML) name their artifact as an endpoint:
    no scheme-specific code exists, so `artifact://my-app:1` and `k8s://host:6443` are
    authorized exactly like `https://host:443`.

    Known limit, pinned here: the target binds the artifact name only. The path inside the
    URL is not part of matching, so `artifact://my-app:1/anything` matches too; scope
    `artifact://app:1` and check `artifact://other-app:1` when the file matters.
    """
    scope = {**make_scope(), "targets": ["artifact://my-app:1", "k8s://10.0.0.5:6443"]}
    assert guard._load_scope(json.dumps(scope).encode(), tmp_path / "scope.json")["targets"]
    assert guard.check_target(scope, "artifact://my-app:1")
    assert guard.check_target(scope, "k8s://10.0.0.5:6443")
    assert guard.check_target(scope, "artifact://my-app:1/Dockerfile")
    assert guard.check_target(scope, "artifact://my-app:2") is False
    assert guard.check_target(scope, "artifact://my-app-1:1") is False
    assert guard.check_target(scope, "https://my-app:1") is False  # scheme is part of it


def test_underscore_slug_target_is_refused(signed):
    """TARGET_RE allows [a-z0-9.-] in the host: `artifact://my_app:1` (a repo slug) must be
    refused by the public verifier, before any command runs, even when correctly signed."""
    signed["scope"].write_text(json.dumps({**make_scope(), "targets": ["artifact://my_app:1"]}))
    signed["sig"].unlink()  # re-sign the new content; ssh-keygen won't overwrite
    subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(signed["key"]),
                    "-n", NAMESPACE, str(signed["scope"])],
                   check=True, cwd=signed["scope"].parent)
    with pytest.raises(guard.ScopeError, match="invalid target"):
        guard.verify_scope(signed["scope"], signed["sig"], signed["pubkey"])

def test_unknown_manifest_field_is_rejected(tmp_path):
    """scope_schema.json is additionalProperties: false."""
    scope = {**make_scope(), "allowRedirects": True}
    with pytest.raises(guard.ScopeError, match="unknown fields"):
        guard._load_scope(json.dumps(scope).encode(), tmp_path / "scope.json")


def test_duplicate_target_is_rejected(tmp_path):
    """scope_schema.json is uniqueItems: true on targets."""
    scope = {**make_scope(), "targets": ["https://example.com:443", "https://example.com:443"]}
    with pytest.raises(guard.ScopeError, match="duplicate"):
        guard._load_scope(json.dumps(scope).encode(), tmp_path / "scope.json")


@pytest.mark.parametrize("expires", [
    "2999-01-01T00:00:00+0000",  # schema wants +HH:MM, not the ambiguous compact form
    "2999-01-01T00:00:00",       # no offset at all
])
def test_expires_at_needs_colon_offset(tmp_path, expires):
    scope = {**make_scope(expires), }
    with pytest.raises(guard.ScopeError, match="expiresAt"):
        guard._load_scope(json.dumps(scope).encode(), tmp_path / "scope.json")


def test_expires_at_colon_offset_is_accepted(tmp_path):
    scope = make_scope("2999-01-01T00:00:00+00:00")
    assert guard._load_scope(json.dumps(scope).encode(), tmp_path / "scope.json")["expiresAt"]


# --- budgets --------------------------------------------------------------

def test_timeout_kills_grandchildren(signed, tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    script = f"sleep 10 & echo $! > {pidfile}; wait"
    started = time.monotonic()
    proc = run_cli(signed, ["--", "bash", "-c", script], max_seconds=1)
    elapsed = time.monotonic() - started
    assert proc.returncode == 124
    assert 1.0 <= elapsed <= 3.0, f"took {elapsed:.2f}s"
    wait_dead(int(pidfile.read_text().strip()))


def test_timeout_kills_setsid_escaped_grandchild(signed, tmp_path):
    pidfile = tmp_path / "escaped.pid"
    pgfile = tmp_path / "groups"
    # Record the escapee's process group (field 5 of /proc/pid/stat) while it still
    # lives, so the test can prove it really left the guard's group.
    script = (f"setsid sleep 30 & p=$!; echo $p > {pidfile}; "
              f"awk '{{print $5}}' /proc/$p/stat > {pgfile}; "
              f"awk '{{print $5}}' /proc/$$/stat >> {pgfile}; wait")
    proc = run_cli(signed, ["--", "bash", "-c", script], max_seconds=1)
    assert proc.returncode == 124
    escaped_pgid, child_pgid = (int(x) for x in pgfile.read_text().split())
    assert escaped_pgid != child_pgid
    wait_dead(int(pidfile.read_text().strip()))


def test_clean_exit_kills_background_grandchild(signed, tmp_path):
    pidfile = tmp_path / "background.pid"
    script = f"sleep 30 & echo $! > {pidfile}; exit 0"
    proc = run_cli(signed, ["--", "bash", "-c", script], max_seconds=10)
    assert proc.returncode == 0
    wait_dead(int(pidfile.read_text().strip()))


def test_preexisting_snapshot_excludes_own_command(tmp_path, monkeypatch):
    """Deterministic form of the load race above: the guard is descheduled right after
    forking, so a descendant that setsid()s at once already exists when the snapshot of
    the caller's children is taken. It must be killed, not protected as 'preexisting'."""
    real_popen = subprocess.Popen

    def slow_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        time.sleep(0.2)  # stand-in for the guard losing the CPU (what load does)
        return proc

    pidfile = tmp_path / "snapshot.pid"
    monkeypatch.setattr(guard.subprocess, "Popen", slow_popen)
    code = guard.run_with_budget(
        ["bash", "-c", f"setsid sleep 30 & echo $! > {pidfile}"], 10, None)
    assert code == 0
    wait_dead(int(pidfile.read_text().strip()))


def test_early_setsid_escapee_dies_under_load(signed, tmp_path):
    """Regression: the caller's-children snapshot was taken after Popen, so the child
    itself (and any descendant it forked that fast) was captured as 'preexisting' and
    survived the sweep. Repeated under CPU load because the race widens with it."""
    load = [subprocess.Popen([sys.executable, "-c", "while True: pass"])
            for _ in range(4)]
    survived = []
    try:
        for i in range(20):
            pidfile = tmp_path / f"early{i}.pid"
            # setsid() at once and leave the guard's process group, then the shell waits
            # so the guard hits the timeout path with the escapee still running.
            proc = run_cli(signed, ["--", "bash", "-c",
                                    f"setsid sleep 30 & echo $! > {pidfile}; wait"],
                           max_seconds=1)
            assert proc.returncode == 124, proc.stderr
            pid = int(pidfile.read_text().strip())
            try:
                wait_dead(pid)
            except AssertionError:
                survived.append(pid)
    finally:
        for proc_ in load:
            proc_.kill()
            proc_.wait()
        for pid in survived:  # never leave the regression's escapees running
            guard._signal(pid, 9)
    assert not survived, f"escaped setsid descendants survived: {survived}"


def test_escaped_holder_of_stdout_does_not_hang_caller(signed, tmp_path):
    """A descendant that keeps stdout open must not wedge the caller's read."""
    script = "setsid sleep 30 & sleep 30"
    started = time.monotonic()
    proc = run_cli(signed, ["--", "bash", "-c", script], max_seconds=1)
    assert proc.returncode == 124
    assert time.monotonic() - started < 8, "guard/caller blocked on the leaked pipe"


def test_stdin_is_devnull(signed):
    proc = run_cli(signed, ["--", "sh", "-c", "test -t 0 && exit 3; read x; echo ok"])
    assert proc.returncode == 0, proc.stderr


def test_disk_budget_aborts(signed, tmp_path):
    work = tmp_path / "diskwork"
    work.mkdir()
    started = time.monotonic()
    proc = run_cli(signed, ["--max-disk-mb", "1", "--cwd", str(work), "--",
                            "bash", "-c", "dd if=/dev/zero of=big bs=1M count=8 "
                                          "status=none; sleep 30"], max_seconds=30)
    assert proc.returncode == 125
    assert time.monotonic() - started < 10


def test_exit_code_propagates(signed):
    proc = run_cli(signed, ["--", "bash", "-c", "exit 7"])
    assert proc.returncode == 7


@pytest.mark.parametrize("extra", [["--max-disk-mb", "1"], []])
def test_disk_budget_without_cwd_is_a_loud_error(signed, tmp_path, extra):
    """A disk budget we cannot measure is an error, not a silent no-op."""
    sentinel = tmp_path / "sentinel"
    proc = run_cli(signed, [*extra, "--", "touch", str(sentinel)], cwd=None)
    assert proc.returncode != 0
    assert "--cwd" in proc.stderr
    assert not sentinel.exists()


@pytest.mark.parametrize("extra", [[], ["--max-disk-mb", "100"]])
def test_manifest_disk_budget_applies_by_default(signed, tmp_path, extra):
    """No flag, or a looser flag: the signed maxDiskMB (10MB) must still abort."""
    work = tmp_path / "manifestdisk"
    work.mkdir()
    started = time.monotonic()
    proc = run_cli(signed, [*extra, "--", "bash", "-c", "dd if=/dev/zero of=big "
                                                "bs=1M count=20 status=none; sleep 30"],
                   max_seconds=30, cwd=work)
    assert proc.returncode == 125, proc.stderr
    assert time.monotonic() - started < 10


# --- process-group hygiene ------------------------------------------------

def test_trap_handler_respawn_is_killed(signed, tmp_path):
    """A child forked *by the signal handler*, after the first sweep, must still die."""
    pidfile = tmp_path / "respawn.pid"
    script = f"trap 'sleep 30 & echo $! > {pidfile}' TERM; sleep 30"
    proc = run_cli(signed, ["--", "bash", "-c", script], max_seconds=1)
    assert proc.returncode == 124
    wait_dead(int(pidfile.read_text().strip()))


def test_foreign_child_keeps_its_exit_code(tmp_path):
    """waitpid(-1) used to reap the caller's children and turn their 42 into a 0."""
    foreign = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(42)"])
    time.sleep(0.3)  # foreign is a zombie by now: a stray waitpid(-1) would steal it
    code = guard.run_with_budget(
        [sys.executable, "-c",
         "import subprocess, sys; subprocess.Popen(['sleep', '5']); sys.exit(7)"],
        10, None)
    assert code == 7  # the direct child's real exit code, not a reaped 0
    assert foreign.wait(timeout=10) == 42


def test_no_killpg_once_the_leader_is_reaped(monkeypatch):
    """After poll() reaped the leader, its pgid may be recycled: never killpg it."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    calls = []
    monkeypatch.setattr(guard.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    guard._kill_group(proc, proc.pid)
    assert calls == []


def test_subreaper_failure_warns_on_stderr(monkeypatch, capsys):
    monkeypatch.setattr(guard, "_become_subreaper", lambda: False)
    assert guard.run_with_budget([sys.executable, "-c", "pass"], 10, None) == 0
    assert "subreaper" in capsys.readouterr().err
