"""The two plugin entries of `.claude-plugin/plugin.json`, asserted as the docker command lines they
are (U5, U4, A1): the file is the only place the shipped container is actually configured, and until
now nothing ever read it as a whole. Both entries must run the *same* image, differ only where the
exec entry has to (air-gapped + `STORYBOARD_ALLOW_EXEC=1` + CAP_SETGID for xterm), and keep the hardening
that makes a rendered page safe to run: read-only root, `--cap-drop ALL`, tmpfs `/tmp` **with exec**
(espeak's `dlopen` dies on the default `noexec` tmpfs -- A1), no privileged escape hatches.

`plugin.json` lives at the repo root, which is *not* in the image this suite normally runs in. So the
path is resolvable two ways: `STORYBOARD_REPO_ROOT` wins, otherwise the repo is assumed above this file
(CI checks the repo out, so `parents[3]` is right there); when neither exists the tests skip instead
of failing. Run them inside the image with the repo mounted read-only:

    docker run --rm -v "$PWD:/repo:ro" -e STORYBOARD_REPO_ROOT=/repo storyboard-video-mcp:<key> \\
        python -m pytest -q tests/test_plugin_entry.py
"""

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(os.environ.get("STORYBOARD_REPO_ROOT") or Path(__file__).resolve().parents[3])
PLUGIN = REPO_ROOT / ".claude-plugin" / "plugin.json"

pytestmark = pytest.mark.skipif(
    not PLUGIN.is_file(), reason=f"no {PLUGIN} (repo root not mounted: set STORYBOARD_REPO_ROOT)")

# Flags that would give the throwaway container a way out of its sandbox.
ESCAPES = ("--privileged", "--userns=host", "--pid=host", "--ipc=host", "--publish", "-p",
           "--security-opt=seccomp=unconfined", "--security-opt=label=disable")

ENTRIES = ("storyboard-video", "storyboard-video-exec")


def _args(name):
    with PLUGIN.open() as f:
        servers = json.load(f)["mcpServers"]
    args = servers[name]["args"]
    assert servers[name]["command"] == "docker", name
    return args


def _flag(args, flag):
    """Values given to `flag`, in order (`--flag value` and `--flag=value` both count)."""
    out = []
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            out.append(args[i + 1])
        elif a.startswith(flag + "="):
            out.append(a.split("=", 1)[1])
    return out


def _mounts(args):
    """`-v` specs by container path: {"/repo": ("${PWD}", "ro"), ...}."""
    out = {}
    for spec in _flag(args, "-v"):
        src, _, rest = spec.partition(":")
        dst, _, mode = rest.partition(":")
        out[dst] = (src, mode)
    return out


def test_one_image_behind_both_entries():
    base, ex = _args("storyboard-video"), _args("storyboard-video-exec")
    assert base[0] == ex[0] == "run"
    assert "-i" in base and "--rm" in base, "stdio server, throwaway container"
    assert base[-1] == ex[-1], "the entries must differ in flags only, not in image"
    assert "storyboard-video-mcp" in base[-1], base[-1]


def test_repo_is_read_only_state_is_a_volume_music_is_read_only():
    for name in ENTRIES:
        mounts = _mounts(_args(name))
        assert mounts["/repo"] == ("${PWD}", "ro"), f"{name}: launch dir (start in the repo root), read-only"
        src, mode = mounts["/work"]
        assert mode not in ("ro", "readonly"), f"{name}: the work volume must be writable"
        assert not src.startswith(("/", "${", ".")), f"{name}: /work is a named volume, got {src!r}"
        assert mounts["/music"] == ("${HOME}/.cache/storyboard-video/music", "ro"), name
        assert mounts["/sfx"] == ("${HOME}/.cache/storyboard-video/sfx", "ro"), name


def test_both_entries_are_hardened():
    for name in ENTRIES:
        args = _args(name)
        assert "--read-only" in args, name
        assert _flag(args, "--cap-drop") == ["ALL"], name
        assert "no-new-privileges" in _flag(args, "--security-opt"), name
        assert [int(v) for v in _flag(args, "--pids-limit")] == [256], name
        assert "/root" in _flag(args, "--tmpfs"), f"{name}: read-only root leaves no writable HOME"
        assert [a for a in args if a in ESCAPES] == [], name


def test_tmp_is_tmpfs_with_exec():
    """The previous engine (espeak-ng) `dlopen`ed a lib it unpacked under TMPDIR, so /tmp stays exec. Pocket TTS
    only writes a temp WAV there; whether `noexec` would now be safe was NOT tested, so the flag is kept."""
    for name in ENTRIES:
        args = _args(name)
        assert "/tmp:rw,exec" in _flag(args, "--tmpfs"), name
        assert not [a for a in args if "espeak" in a], f"{name}: the /run/espeak detour is not the fix"


def test_only_the_exec_entry_is_air_gapped_and_may_exec():
    base, ex = _args("storyboard-video"), _args("storyboard-video-exec")
    assert _flag(ex, "--network") == ["none"]
    assert _flag(base, "--network") == [], "the base entry still reaches host.docker.internal"
    assert _flag(ex, "-e") == ["STORYBOARD_ALLOW_EXEC=1"]
    assert "STORYBOARD_ALLOW_EXEC" not in " ".join(base), "exec off by default"
    # xterm needs CAP_SETGID; it is dropped with ALL and added back on the exec entry only
    assert _flag(ex, "--cap-add") == ["SETGID"]
    assert _flag(base, "--cap-add") == []
    assert _flag(base, "--add-host") == ["host.docker.internal:host-gateway"]
    assert _flag(ex, "--add-host") == []
