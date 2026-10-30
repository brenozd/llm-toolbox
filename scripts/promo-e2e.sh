#!/usr/bin/env bash
# promo-e2e.sh -- the whole shipped path, unattended (U5): read `.claude-plugin/plugin.json`, expand
# `${PWD}`/`${HOME}` the way Claude Code's launcher does, run that entry's verbatim `docker run` argv and
# drive the MCP server over stdio. Nothing is mocked: real container, real image, real ffmpeg/Kokoro.
#
#     scripts/promo-e2e.sh                          # the `promo-video` entry
#     PROMO_E2E_ENTRY=promo-video-exec scripts/...  # the air-gapped entry (same code path)
#     PROMO_E2E_IMAGE=promo-video-mcp:local scripts/...   # test an image before it is published
#
# Steps (a failure at any one of them exits non-zero and prints the server log's tail):
#   initialize -> tools/list -> validate_spec -> stills -> narrate -> render(draft) -> verify
#
# Two hard preconditions, both checked before docker starts: `${PWD}` must be the repo root (that is
# what the entry mounts at `/repo`, read-only) and `~/.cache/promo-video/music` must already exist --
# `docker run -v` would otherwise create it root-owned on the host and the music skill could not write.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"  # ${PWD} of the entry is the launch directory: start where the mount points

command -v docker >/dev/null || { echo "promo-e2e: docker not found in PATH" >&2; exit 127; }
command -v python3 >/dev/null || { echo "promo-e2e: python3 not found in PATH" >&2; exit 127; }
if [ ! -d "${HOME}/.cache/promo-video/music" ]; then
    echo "promo-e2e: ${HOME}/.cache/promo-video/music is missing (docker would create it root-owned)." >&2
    echo "promo-e2e: mkdir -p \"\$HOME/.cache/promo-video/music\" and re-run." >&2
    exit 2
fi

exec python3 - "$ROOT" <<'PY'
"""MCP client for the promo-video stdio server: stdlib only, so the host needs no `mcp` package.

The transport is newline-delimited JSON-RPC 2.0, which is what the server writes; a reader thread
feeds the messages to a queue so every wait can time out instead of hanging the run.
"""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(sys.argv[1])
ENTRY = os.environ.get("PROMO_E2E_ENTRY", "promo-video")
TIMEOUT = float(os.environ.get("PROMO_E2E_TIMEOUT", "600"))  # per call, not for the whole run
PROTOCOL = "2025-06-18"  # the server answers with the version it supports; either direction is fine

# A tiny *draft* spec: a title, a bullet list with real evidence, a code scene and a terminal scene.
# 16:9, 10 fps, four ~2.5 s scenes => ~110 frames at half size, so the whole run stays under a minute.
# Paths that must exist are repo-relative (`README.md`), which proves the `/repo` mount is the repo.
SPEC = {
    "fps": 10,
    "aspect": "16:9",
    "lang": "pt-BR",
    "direction": {"purpose": "feature-demo", "tone": "calm technical",
                  "palette": {"bg": "#0f1115", "fg": "#f2f4f8", "accent": "#4cc2ff"},
                  "palette_source": "user", "audio": "voice"},
    "scenes": [
        {"id": "hook", "type": "title", "title": "promo-video", "subtitle": "e2e do plugin.json",
         "duration_s": 2.5, "narration": "O próprio servidor monta este vídeo."},
        {"id": "why", "type": "bullets", "heading": "O que ele faz", "evidence": "README.md:5",
         "items": ["captura real", "legenda honesta", "vídeo verificado"], "duration_s": 3,
         "narration": "Cada cena nasce de uma captura de verdade."},
        {"id": "src", "type": "code", "code": "docker run -i --rm promo-video-mcp",
         "source": "README.md:1-6", "duration_s": 2.5,
         "narration": "O container sobe sem estado nenhum."},
        {"id": "run", "type": "terminal", "heading": "rodando",
         "lines": ["$ scripts/promo-e2e.sh", "promo-e2e: ok"], "duration_s": 2.5,
         "narration": "Um único script fecha o ciclo completo."},
    ],
}


class Fail(Exception):
    pass


def docker_argv(entry):
    """The entry's argv with `${VAR}` expanded, exactly as the launcher hands it to docker."""
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    cfg = plugin["mcpServers"].get(entry)
    if cfg is None:
        raise Fail(f"no mcpServers[{entry!r}] in .claude-plugin/plugin.json")
    known = {"PWD": str(ROOT), "HOME": os.environ.get("HOME", "")}

    def sub(m):
        name = m.group(1) or m.group(2)
        if name in known:
            return known[name]
        if name in os.environ:
            return os.environ[name]
        raise Fail(f"cannot expand ${{{name}}} in plugin.json: not set in this shell")

    argv = [cfg["command"]] + [re.sub(r"\$\{(\w+)\}|\$(\w+)", sub, a) for a in cfg["args"]]
    if os.environ.get("PROMO_E2E_IMAGE"):
        argv[-1] = os.environ["PROMO_E2E_IMAGE"]
    return argv


class Client:
    def __init__(self, argv, log_path):
        self.log_path = log_path
        self.log = open(log_path, "wb")
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.log, bufsize=0)
        self.q = queue.Queue()
        self.seq = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.q.put(json.loads(line))
            except ValueError:
                pass  # a log line on stdout is not a protocol error
        self.q.put(None)  # the stream closed: every waiter must stop

    def _send(self, msg):
        try:
            self.p.stdin.write((json.dumps(msg) + "\n").encode())
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            raise Fail(f"the server died (see {self.log_path})")

    def request(self, method, params=None):
        self.seq += 1
        rid = self.seq
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        end = time.time() + TIMEOUT
        while True:
            left = end - time.time()
            if left <= 0:
                raise Fail(f"{method}: no answer in {TIMEOUT:g}s")
            try:
                msg = self.q.get(timeout=min(left, 1.0))
            except queue.Empty:
                continue
            if msg is None:
                raise Fail(f"{method}: the server closed the stream (see {self.log_path})")
            if msg.get("id") != rid:
                continue  # a notification or a log record
            if "error" in msg:
                raise Fail(f"{method}: {msg['error'].get('message')}")
            return msg["result"]

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def call(self, tool, arguments):
        res = self.request("tools/call", {"name": tool, "arguments": arguments})
        if res.get("isError"):
            raise Fail(f"{tool} raised: {json.dumps(res)[:300]}")
        for item in res.get("content", []):
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except ValueError:
                    continue
        if isinstance(res.get("structuredContent"), dict):
            return res["structuredContent"]
        raise Fail(f"{tool}: no JSON in the result")

    def close(self):
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.p.terminate()
        self.log.close()


def ok(step, payload, **must):
    """Every tool answers with its own status; a step that is not `ok` is a failed run."""
    if payload.get("status") != "ok":
        raise Fail(f"{step}: status {payload.get('status')!r} {json.dumps(payload)[:300]}")
    for key, want in must.items():
        if key in payload and payload[key] != want:
            raise Fail(f"{step}: {key} = {payload[key]!r}, expected {want!r}")
    return payload


def main():
    argv = docker_argv(ENTRY)
    print(f"promo-e2e: entry {ENTRY}, image {argv[-1]}")
    log_path = os.environ.get("PROMO_E2E_LOG", "/tmp/promo-e2e-server.log")
    c = Client(argv, log_path)
    try:
        init = c.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                        "clientInfo": {"name": "promo-e2e", "version": "1"}})
        print(f"promo-e2e: server {init['serverInfo']['name']} {init['serverInfo']['version']} "
              f"(protocol {init.get('protocolVersion')})")
        c.notify("notifications/initialized")

        tools = {t["name"] for t in c.request("tools/list")["tools"]}
        missing = {"validate_spec", "stills", "narrate", "render", "render_status", "verify"} - tools
        if missing:
            raise Fail(f"tools/list is missing {sorted(missing)}")
        print(f"promo-e2e: {len(tools)} tools")

        spec = ok("validate_spec", c.call("validate_spec", {"spec": SPEC}), status="ok")
        errors = [f for f in spec.get("findings", []) if f.get("severity") == "error"]
        if errors:
            raise Fail(f"validate_spec: {json.dumps(errors)[:400]}")
        h = spec["spec_hash"]
        print(f"promo-e2e: validate_spec ok, spec_hash {h}, {spec['duration_s']}s")

        still = ok("stills", c.call("stills", {"spec_hash": h}))
        if still.get("audit_warnings"):
            raise Fail(f"stills: {still['audit_warnings']} layout warnings, fix the spec: "
                       f"{json.dumps([r.get('findings') for r in still['stills']])[:400]}")
        shots = [r for r in still["stills"] if r.get("path")]
        if len(shots) != len(SPEC["scenes"]):
            raise Fail(f"stills: {len(shots)} images for {len(SPEC['scenes'])} scenes")
        print(f"promo-e2e: stills ok, {len(shots)} frames")

        voice = ok("narrate", c.call("narrate", {"spec_hash": h}))
        if not voice.get("total_s"):
            raise Fail(f"narrate: no audio measured: {json.dumps(voice)[:300]}")
        print(f"promo-e2e: narrate ok, {voice['total_s']}s of speech "
              f"({voice['synthesized']} synthesized, {voice['cached']} cached)")

        job = ok("render", c.call("render", {"spec_hash": h, "quality": "draft"}))["job_id"]
        end = time.time() + TIMEOUT
        while True:
            st = c.call("render_status", {"job_id": job})
            if st.get("status") == "done":
                break
            if st.get("status") == "error":
                raise Fail(f"render: {st.get('error')}")
            if time.time() > end:
                raise Fail(f"render: job {job} still {st.get('progress')} after {TIMEOUT:g}s")
            time.sleep(2)
        rec = st["result"]
        print(f"promo-e2e: render ok, {rec['width']}x{rec['height']} {rec['frames']} frames -> {rec['video']}")

        ver = ok("verify", c.call("verify", {"video": rec["video"], "spec_hash": h}))
        bad = [f for f in ver.get("findings", []) if f.get("severity") == "error"]
        if bad:
            raise Fail(f"verify: {json.dumps(bad)[:400]}")
        mode = "narrated" if ver.get("narrated") else "silent"
        print(f"promo-e2e: verify ok, {mode}, {ver.get('expected_duration_s')}s, "
              f"audio {ver.get('audio')}, loudness {ver.get('loudness')}")

        print("promo-e2e: ok")
        for key in ("video", "srt", "poster"):
            print(f"  {key}: {rec[key]}")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as e:
        print(f"promo-e2e: FAIL {e}", file=sys.stderr)
        log = os.environ.get("PROMO_E2E_LOG", "/tmp/promo-e2e-server.log")
        try:
            tail = Path(log).read_text(errors="replace").splitlines()[-15:]
        except OSError:
            tail = []
        if tail:
            print(f"promo-e2e: last lines of {log}:", file=sys.stderr)
            print("\n".join(tail), file=sys.stderr)
        sys.exit(1)
PY
