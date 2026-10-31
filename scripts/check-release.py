#!/usr/bin/env python3
"""Assert that a published storyboard-video-mcp tag is the image this repo builds.

Optional: stdlib only, needs network + anonymous pull on the registry, and is
deliberately NOT wired into CI (CI cannot see the registry after it pushes).

    scripts/check-release.py                 # harbor.bzd.gg/bzd/storyboard-video-mcp:latest
    scripts/check-release.py --tag sha-abc123
    scripts/check-release.py --self-test     # offline: unit-tests the comparison logic

Two checks, both regressions seen on 2026-10 (`harbor.bzd.gg` was 4 commits
behind because the build step's path filter never matched):
  1. the tag is a single `linux/amd64` manifest, not a multi-arch index
     (`.woodpecker/build.yaml` builds `platforms: linux/amd64` only);
  2. every `ENV` in `servers/storyboard-video/Dockerfile` (with `$VAR` expanded the
     way the build expands it) has the same value in the published image config.
Extra image Env entries are reported, not failed: they come from the base image
(python:3.12-slim adds PATH/LANG/PYTHON_VERSION/...), so they cannot be checked
without pinning the base image.
Exit: 0 = published tag matches, 1 = mismatch or error (message says which).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

IMAGE = "harbor.bzd.gg/bzd/storyboard-video-mcp"
TAG = "latest"
PLATFORM = "linux/amd64"
ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "servers/storyboard-video/Dockerfile"

MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
ACCEPT = ", ".join(INDEX_TYPES + MANIFEST_TYPES)
VAR = re.compile(r"\$(?:\{(\w+)\}|(\w+))")

# ---------------------------------------------------------------- comparison logic


def dockerfile_env(text: str) -> dict[str, str]:
    """ENV instructions of a Dockerfile in build order, `$VAR` expanded from earlier ENVs.

    Handles `ENV K=V K2=V2`, `ENV K V` (legacy) and backslash continuations. A
    `$VAR` that is not set by a previous ENV is left literal (a base-image var),
    so a mismatch on it is reported instead of silently comparing against ''.
    """
    env: dict[str, str] = {}
    logical = re.sub(r"\\\r?\n", " ", text)
    for line in logical.splitlines():
        s = line.strip()
        if not s.upper().startswith("ENV "):
            continue
        parts = shlex.split(s[4:])
        if parts and "=" not in parts[0]:
            env[parts[0]] = _expand(" ".join(parts[1:]), env)
            continue
        for part in parts:
            key, _, value = part.partition("=")
            env[key] = _expand(value, env)
    return env


def _expand(value: str, env: dict[str, str]) -> str:
    return VAR.sub(lambda m: env.get(m.group(1) or m.group(2), m.group(0)), value)


def platform_of(entry: dict) -> str:
    """`linux/amd64` from a manifest-list entry ('' when the entry has no platform)."""
    p = entry.get("platform") or {}
    os_, arch, variant = p.get("os"), p.get("architecture"), p.get("variant")
    if not os_ or not arch:
        return ""
    return f"{os_}/{arch}/{variant}" if variant else f"{os_}/{arch}"


def manifest_problems(manifest: dict, expected: str = PLATFORM) -> tuple[list[str], list[str]]:
    """(errors, notes) for one registry manifest: single-platform manifest or index."""
    entries = manifest.get("manifests")
    if entries is None:
        return [], ["single-image manifest (not a multi-arch index)"]
    plats = [p for p in map(platform_of, entries) if p and not p.startswith("unknown/")]
    if not plats:  # attestation-only index: report what is there
        return [f"index has no platform entry for {expected}"], []
    errors, notes = [], [f"index platforms: {', '.join(sorted(set(plats)))}"]
    if expected not in plats:
        errors.append(f"index has no {expected} entry")
    others = sorted(set(plats) - {expected})
    if others:
        errors.append(
            f"multi-arch index ({', '.join(others)}): .woodpecker/build.yaml builds {expected} only,"
            " so this tag was published before the platform fix"
        )
    return errors, notes


def env_problems(expected: dict[str, str], published: list[str]) -> tuple[list[str], list[str]]:
    """(errors, notes) comparing Dockerfile ENV (expected) with image config `Env`."""
    got: dict[str, str] = {}
    for item in published:
        key, _, value = item.partition("=")
        got[key] = value
    errors = [
        f"Dockerfile sets {k}={v!r} but the image has no {k}"
        if k not in got
        else f"{k}={got[k]!r} in the image, Dockerfile says {v!r}"
        for k, v in expected.items()
        if got.get(k) != v
    ]
    notes = [
        f"{k}={got[k]!r} is not in the Dockerfile (base image, or from an older Dockerfile)"
        for k in sorted(set(got) - set(expected))
    ]
    return errors, notes

# ---------------------------------------------------------------- registry access


def _json(url: str, accept: str, repo: str, timeout: int) -> dict:
    def get(token: str | None = None):
        headers = {"Accept": accept}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)

    try:
        with get() as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code != 401:  # 404 → caller reports the URL
            raise
        challenge = e.headers.get("WWW-Authenticate", "")
    with get(_bearer(challenge, repo, timeout)) as response:
        return json.load(response)


def _bearer(challenge: str, repo: str, timeout: int) -> str:
    """Anonymous pull token from a `WWW-Authenticate: Bearer realm=...` challenge."""
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = params.get("realm")
    if not realm:
        raise RuntimeError(f"registry wants auth but sent no realm: {challenge!r}")
    query = {"scope": f"repository:{repo}:pull"}
    if params.get("service"):
        query["service"] = params["service"]
    url = f"{realm}?{urllib.parse.urlencode(query)}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)["token"]


def image_env(host: str, repo: str, manifest: dict, timeout: int) -> list[str]:
    """`config.Env` of the manifest (or of the `linux/amd64` entry when it is an index)."""
    if "manifests" in manifest:
        digest = next((e["digest"] for e in manifest["manifests"] if platform_of(e) == PLATFORM), None)
        if digest is None:  # manifest_problems already reported the missing platform
            return []
        manifest = _json(f"https://{host}/v2/{repo}/manifests/{digest}", ACCEPT, repo, timeout)
    config = _json(f"https://{host}/v2/{repo}/blobs/{manifest['config']['digest']}",
                   "application/octet-stream", repo, timeout)
    return config.get("config", {}).get("Env", [])

# ---------------------------------------------------------------- commands


def check_release(image: str, tag: str, dockerfile: Path, timeout: int) -> int:
    host, _, repo = image.partition("/")
    if not repo:
        print(f"✗ --image needs a registry host: {image!r}", file=sys.stderr)
        return 1
    expected = dockerfile_env(dockerfile.read_text())
    print(f"checking {image}:{tag} against {dockerfile}")
    try:
        manifest = _json(f"https://{host}/v2/{repo}/manifests/{tag}", ACCEPT, repo, timeout)
        errors, notes = manifest_problems(manifest)
        published = image_env(host, repo, manifest, timeout)
    except urllib.error.HTTPError as e:
        print(f"✗ registry: HTTP {e.code} for {image}:{tag} ({e.reason})", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, RuntimeError, KeyError, ValueError) as e:
        print(f"✗ registry: {e}", file=sys.stderr)
        return 1

    env_errors, env_notes = env_problems(expected, published)
    errors += env_errors
    for note in notes + env_notes:
        print(f"  · {note}")
    for error in errors:
        print(f"✗ {error}", file=sys.stderr)
    if errors:
        print(f"✗ {image}:{tag} is NOT the image this commit builds"
              f" ({len(expected)} Dockerfile ENVs checked). Re-run the pipeline;"
              " the tag is stale or was pushed by another commit.", file=sys.stderr)
        return 1
    print(f"✓ {image}:{tag} is {PLATFORM} and matches {len(expected)} Dockerfile ENVs")
    return 0


SELFTEST_DOCKERFILE = """\
FROM python:3.12-slim
ENV ONE=1
ENV TWO=2 THREE=three
ENV LEGACY some value with spaces
ENV BASE=$KOKORO_DIR/model.onnx \\
    EXT=$KOKORO_DIR/ext.bin \\
    LITERAL=$NOT_SET
ENV KOKORO_DIR=/opt/kokoro
ENV KOKORO_DIR=/opt/kokoro
RUN echo ENV NOPE=1
"""


def self_test() -> int:
    """Offline unit tests for the parsing + comparison logic (no network)."""
    failures: list[str] = []
    total = 0

    def check(name: str, got, want) -> None:
        nonlocal total
        total += 1
        if got != want:
            failures.append(f"{name}: got {got!r}, want {want!r}")

    env = dockerfile_env(SELFTEST_DOCKERFILE)
    check("multi-pair ENV", (env["TWO"], env["THREE"]), ("2", "three"))
    check("legacy ENV", env["LEGACY"], "some value with spaces")
    check("continuation + forward", env["LITERAL"], "$NOT_SET")
    check("late var stays literal", env["BASE"], "$KOKORO_DIR/model.onnx")
    check("RUN not parsed", "NOPE" in env, False)

    late = dockerfile_env("ENV KOKORO_DIR=/opt/kokoro\nENV M=$KOKORO_DIR/v.bin B=${KOKORO_DIR}/x\n")
    check("expansion", (late["M"], late["B"]), ("/opt/kokoro/v.bin", "/opt/kokoro/x"))

    good = ["PATH=/usr/bin", "KOKORO_DIR=/opt/kokoro", "M=/opt/kokoro/v.bin"]
    check("env match",
          env_problems({"KOKORO_DIR": "/opt/kokoro"}, good),
          ([], ["M='/opt/kokoro/v.bin' is not in the Dockerfile (base image, or from an older Dockerfile)",
                "PATH='/usr/bin' is not in the Dockerfile (base image, or from an older Dockerfile)"]))
    check("env mismatch", env_problems({"K": "$1:/opt"}, ["K=/opt"])[0], ["K='/opt' in the image, Dockerfile says '$1:/opt'"])
    check("env missing", env_problems({"GONE": "1"}, good)[0], ["Dockerfile sets GONE='1' but the image has no GONE"])
    check("env empty published", env_problems({"K": "v"}, [])[0], ["Dockerfile sets K='v' but the image has no K"])

    index = {"manifests": [{"digest": "sha256:a", "platform": {"os": "linux", "architecture": "amd64"}},
                           {"digest": "sha256:b", "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}}]}
    check("multi-arch index", manifest_problems(index)[0][0].split(":")[0], "multi-arch index (linux/arm64/v8)")
    single = {"manifests": [{"digest": "sha256:a", "platform": {"os": "linux", "architecture": "amd64"}},
                            {"digest": "sha256:c", "platform": {"os": "unknown", "architecture": "unknown"}}]}
    check("attestation ignored", manifest_problems(single)[0], [])
    image_manifest = {"config": {"digest": "sha256:d"}, "layers": []}
    check("single manifest ok", manifest_problems(image_manifest), ([], ["single-image manifest (not a multi-arch index)"]))
    check("missing amd64", manifest_problems({"manifests": [{"digest": "x", "platform": {"os": "linux", "architecture": "arm64"}}]})[0][0],
          "index has no linux/amd64 entry")

    real = dockerfile_env(DOCKERFILE.read_text())
    check("real Dockerfile TTS", real.get("STORYBOARD_TTS_BIN"), "/opt/pocket-tts/pocket-tts")
    check("real Dockerfile playwright", real.get("PLAYWRIGHT_BROWSERS_PATH"), "/ms-playwright")
    check("real Dockerfile no stale ENV", "STORYBOARD_CHROMIUM" in real, False)

    for failure in failures:
        print(f"✗ self-test {failure}", file=sys.stderr)
    print(f"✓ self-test: {total} checks, {len(failures)} failure(s)")
    return int(bool(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", default=IMAGE, help=f"registry repository (default {IMAGE})")
    parser.add_argument("--tag", default=TAG, help=f"tag to check (default {TAG})")
    parser.add_argument("--dockerfile", type=Path, default=DOCKERFILE,
                        help=f"Dockerfile whose ENV must match (default {DOCKERFILE.relative_to(ROOT)})")
    parser.add_argument("--timeout", type=int, default=30, help="per-request timeout in seconds")
    parser.add_argument("--self-test", action="store_true", help="run the offline unit tests and exit")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # keep prints ordered against stderr in pipes
    if args.self_test:
        return self_test()
    return check_release(args.image, args.tag, args.dockerfile, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
