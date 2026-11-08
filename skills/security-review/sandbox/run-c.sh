#!/usr/bin/env bash
# Binary-c profile: no network, read-only root, /work is a size-limited tmpfs.
# usage: run-c.sh [WORKDIR] [--] CMD...
#   CONTAINER_RUNTIME=docker|podman   (default: docker if present, else podman)
#   SANDBOX_IMAGE=security-review-sandbox:local
#   WORKDIR defaults to ./work; it is mounted read-write at /out so results survive
#   the container (the /work tmpfs itself is discarded).
set -euo pipefail

RUNTIME=${CONTAINER_RUNTIME:-$(command -v docker || command -v podman || true)}
IMAGE=${SANDBOX_IMAGE:-security-review-sandbox:local}
WORKDIR=${1:-${WORKDIR:-$PWD/work}}; shift || true
if [[ ${1:-} == "--" ]]; then shift; fi
[[ $# -gt 0 ]] || set -- bash
[[ -n $RUNTIME ]] || { echo "no container runtime (docker/podman)" >&2; exit 1; }
mkdir -p "$WORKDIR"

# SYS_PTRACE is the only capability added back: gdb and `frida -f` (child injection)
# need to ptrace a process they spawn. Everything else stays dropped.
"$RUNTIME" run --rm -i \
  --network none \
  --cap-drop ALL --cap-add SYS_PTRACE \
  --security-opt no-new-privileges --read-only \
  --tmpfs /work:rw,exec,size=512m,mode=1777 \
  --tmpfs /tmp:rw,exec,size=64m \
  --shm-size 64m --cpus 1 --pids-limit 256 \
  -e HOME=/tmp \
  -e AFL_SKIP_CPUFREQ=1 \
  -e AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1 \
  -e ASAN_OPTIONS=detect_leaks=0 \
  -v "$WORKDIR:/out:rw" \
  "$IMAGE" "$@"
