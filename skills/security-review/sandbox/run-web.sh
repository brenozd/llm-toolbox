#!/usr/bin/env bash
# Web-recon profile: the tool container has no route out. A dual-homed sidecar proxy
# is the only egress, and its allowlist comes from the signed scope.
#
# usage: run-web.sh SCOPE.json SCOPE.sig PUBKEY [-- CMD...]
#   CONTAINER_RUNTIME=docker|podman   (default: docker if present, else podman)
#   SANDBOX_IMAGE=security-review-sandbox:local
#   WORKDIR=$PWD                      host dir mounted read-only at /work
#   OUT_DIR=$(mktemp -d)              host dir mounted read-write at /work-out; its path
#                                     is printed, so output survives --rm. mktemp's 0700
#                                     is kept: the tool runs as --user $(id -u):$(id -g),
#                                     so it writes there as you. A caller's dir is left
#                                     as-is (a warning if it is not writable).
#   EGRESS_NETWORK                    the proxy's second network (default bridge/podman)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RUNTIME=${CONTAINER_RUNTIME:-$(command -v docker || command -v podman || true)}
IMAGE=${SANDBOX_IMAGE:-security-review-sandbox:local}
WORKDIR=${WORKDIR:-$PWD}
OUT_DIR=${OUT_DIR:-}
if [[ -n $OUT_DIR ]]; then
  # The caller's directory: their permissions are theirs, not ours to widen.
  [[ -d $OUT_DIR ]] || mkdir -p "$OUT_DIR"
  [[ -w $OUT_DIR ]] || echo "warning: OUT_DIR $OUT_DIR is not writable; the tool cannot write output" >&2
else
  OUT_DIR=$(mktemp -d -t sr-out-XXXXXX)
fi
[[ $# -ge 3 ]] || { echo "usage: $0 SCOPE.json SCOPE.sig PUBKEY [-- CMD...]" >&2; exit 2; }
SCOPE=$1 SIG=$2 PUBKEY=$3; shift 3
if [[ ${1:-} == "--" ]]; then shift; fi
[[ $# -gt 0 ]] || set -- bash

if [[ -z $RUNTIME ]]; then echo "no container runtime (docker/podman)" >&2; exit 1; fi
if [[ $RUNTIME == *podman ]]; then
  EGRESS_NETWORK=${EGRESS_NETWORK:-podman}
else
  EGRESS_NETWORK=${EGRESS_NETWORK:-bridge}
fi
SUFFIX=$$
INTERNAL=security-review-internal-$SUFFIX  # per run: concurrent runs must not share it
PROXY=sr-proxy-$SUFFIX

TMP=$(mktemp -d)
cleanup() {
  "$RUNTIME" rm -f "$PROXY" >/dev/null 2>&1 || true
  "$RUNTIME" network rm "$INTERNAL" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

# 1. Verify the signed scope; nothing runs if this fails.
GUARD_DIR="$SCRIPT_DIR/../scripts" python3 - "$SCOPE" "$SIG" "$PUBKEY" "$TMP/scope.json" <<'PY'
import json, os, sys
sys.path.insert(0, os.environ["GUARD_DIR"])
import guard
json.dump(guard.verify_scope(*sys.argv[1:4]), open(sys.argv[4], "w"))
PY

# 2. Allowlist = exactly the scope's http targets, IPs pinned now.
python3 "$SCRIPT_DIR/gen-proxy-conf.py" --scope "$TMP/scope.json" --out "$TMP/proxy.json"

# 3. Internal network for the tool, egress network for the proxy's other leg.
"$RUNTIME" network inspect "$INTERNAL" >/dev/null 2>&1 || "$RUNTIME" network create --internal "$INTERNAL" >/dev/null

"$RUNTIME" run -d --rm --name "$PROXY" --network "$INTERNAL" --network-alias proxy \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /tmp --pids-limit 256 \
  -v "$TMP/proxy.json:/etc/proxy.json:ro" \
  -v "$SCRIPT_DIR/egress_proxy.py:/opt/egress_proxy.py:ro" \
  "$IMAGE" python3 /opt/egress_proxy.py --config /etc/proxy.json --listen 0.0.0.0:8888 >/dev/null
"$RUNTIME" network connect "$EGRESS_NETWORK" "$PROXY"

for _ in $(seq 1 50); do
  "$RUNTIME" logs "$PROXY" 2>&1 | grep -q listening && break
  sleep 0.2
done

# 4. The tool: internal network only, HTTP through the proxy, HTTPS explicitly empty.
#    The source tree is :ro; only OUT_DIR is writable, and it outlives the container.
#    --user (host uid:gid): output files belong to the caller, not to container root.
#    --user also drops supplementary groups, so re-add them: an OUT_DIR shared through a
#    secondary group (chgrp, mode 0770) is otherwise unwritable from inside.
GROUP_ARGS=""
for g in $(id -G); do [[ $g == "$(id -g)" ]] || GROUP_ARGS+=" --group-add $g"; done

echo "sandbox output dir: $OUT_DIR" >&2
rc=0
"$RUNTIME" run --rm -i --network "$INTERNAL" \
  --user "$(id -u):$(id -g)" $GROUP_ARGS \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,exec,size=64m,mode=1777 --pids-limit 256 \
  -e HOME=/tmp \
  -e http_proxy=http://proxy:8888 -e HTTP_PROXY=http://proxy:8888 \
  -e https_proxy= -e HTTPS_PROXY= -e no_proxy= -e NO_PROXY= \
  -v "$WORKDIR:/work:ro" \
  -v "$OUT_DIR:/work-out:rw" \
  -e SANDBOX_OUT=/work-out \
  "$IMAGE" "$@" || rc=$?

# A scan of nothing is not coverage: nuclei exits 0 when every probe is skipped (port
# closed/filtered), so require one request through the proxy before passing a nuclei run.
if [[ $rc == 0 && ${1##*/} == nuclei ]] &&
   ! "$RUNTIME" logs "$PROXY" 2>&1 | grep -q 'decision=ALLOW'; then
  echo "run-web.sh: nuclei sent no request through the proxy - a scan of nothing is not coverage" >&2
  exit 1
fi
exit "$rc"
