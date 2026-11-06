#!/usr/bin/env python3
"""Lazy MCP shim: keep the docker MCP server stopped until a tool is actually called.

    lazy-mcp.py --name <entry> [--refresh] -- docker run -i --rm ... image:tag

The client sees a normal stdio MCP server. `initialize`, the `*/list` calls and
`ping` are answered from a cache written by an earlier run, so session start does
not pay `docker run`/`docker pull`; the first request that needs the real server
(typically `tools/call`) spawns it, and it is stopped again after idling.

Env:
  LAZY_MCP_IDLE_SECONDS  stop the server after this much idle time (default 600, 0 = never)
  LAZY_MCP_CACHE_DIR     cache directory (default ${XDG_CACHE_HOME:-~/.cache}/llm-toolbox/lazy-mcp)

Stdlib only, Python 3.9+. Never chdir's: the docker args may mount ${PWD}.
"""
from __future__ import annotations

import argparse
import collections
import copy
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

SCHEMA = 1
INTERNAL = "lazy-mcp:"
DEFAULT_IDLE = 600.0
INIT_TIMEOUT = 180.0
LIST_TIMEOUT = 60.0
POLL = 0.25
STOP_WAIT = 10.0
KILL_WAIT = 5.0
STDERR_TAIL = 20
# request method -> (cache field, list result field)
LISTS = {
    "tools/list": ("tools", "tools"),
    "resources/list": ("resources", "resources"),
    "resources/templates/list": ("resourceTemplates", "resourceTemplates"),
    "prompts/list": ("prompts", "prompts"),
}
LIST_KEYS = ("tools", "resources", "resourceTemplates", "prompts")
MISS = object()


def _slot(value: str) -> str:
    """Filesystem-safe fragment for a cache file name."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", value) or "_"


def cache_root() -> str:
    explicit = os.environ.get("LAZY_MCP_CACHE_DIR")
    if explicit:
        return explicit
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "llm-toolbox", "lazy-mcp")


def image_tag(argv: list[str]) -> str:
    """Last argv element is the image; its tag keeps two versions apart in the cache."""
    last = argv[-1] if argv else ""
    # shortcut: an untagged image is stored under "latest" instead of being parsed away
    return last.rsplit(":", 1)[1] if ":" in last else "latest"


def patch_capabilities(result: dict) -> dict:
    """Same server, but we can push updates: the cache gets rewritten on change."""
    caps = result.setdefault("capabilities", {})
    caps.setdefault("tools", {})["listChanged"] = True
    return result


def tail_of(tail: str) -> str:
    """Child stderr tail, as a suffix for an error message."""
    return f" ({tail})" if tail else ""


def _dumps(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


class SpawnError(Exception):
    """The child could not be started or did not answer the handshake."""


class Cache:
    """<dir>/<name>-<tag>.json, mode 0600 in a 0700 directory, replaced atomically."""

    def __init__(self, name: str, argv: list[str]) -> None:
        self.dir = cache_root()
        self.name = name
        self.image = argv[-1] if argv else ""
        self.path = os.path.join(self.dir, f"{_slot(name)}-{_slot(image_tag(argv))}.json")

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            return None
        if data.get("name") != self.name:
            return None
        return data

    def build(self, initialize: dict, lists: dict) -> dict:
        data = {
            "schema": SCHEMA,
            "name": self.name,
            "image": self.image,
            "saved": int(time.time()),
            "initialize": initialize,
        }
        data.update({k: lists.get(k) for k in LIST_KEYS})
        return data

    def save(self, data: dict) -> None:
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        tmp = f"{self.path}.tmp{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        os.replace(tmp, self.path)
        self._drop_stale()

    def _drop_stale(self) -> None:
        """One cache file per entry: a new image tag invalidates the old one.

        The file name is only a cheap prefilter. Whether a file belongs to this entry
        is decided by the `name` field inside it, because entries whose names share a
        prefix (`storyboard-video` vs `storyboard-video-exec`) share this directory.
        """
        prefix = _slot(self.name) + "-"
        try:
            names = os.listdir(self.dir)
        except OSError:
            return
        for name in names:
            path = os.path.join(self.dir, name)
            if not (name.startswith(prefix) and name.endswith(".json")) or path == self.path:
                continue
            if self._belongs_to_us(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _belongs_to_us(self, path: str) -> bool:
        """Read the cache file's own `name`; never trust the file name alone."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False  # unreadable: leave it, it may be another entry's cache
        return isinstance(data, dict) and data.get("name") == self.name


class Shim:
    def __init__(self, name: str, argv: list[str]) -> None:
        self.name = name
        self.argv = list(argv)
        self.cache = Cache(name, self.argv)
        self.cached = self.cache.load()
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.out_lock = threading.Lock()
        self.in_lock = threading.Lock()
        self.state = "idle"  # idle | starting | running
        self.proc = None
        self.container = None
        self.queue = []  # (msg, raw line) waiting for a spawn, flushed in order
        self.inflight = set()
        self.client_params = None
        self.internal = {}
        self.seq = 0
        self.spawns = 0
        self.last_activity = time.time()
        self.stderr_tail = collections.deque(maxlen=STDERR_TAIL)
        self.closing = False
        self.idle = self._idle_seconds()

    @staticmethod
    def _idle_seconds() -> float:
        raw = os.environ.get("LAZY_MCP_IDLE_SECONDS", "")
        if not raw.strip():
            return DEFAULT_IDLE
        try:
            return max(0.0, float(raw))
        except ValueError:
            return DEFAULT_IDLE

    # -- client side -------------------------------------------------------
    def _write(self, msg: dict) -> None:
        with self.out_lock:
            sys.stdout.write(_dumps(msg) + "\n")
            sys.stdout.flush()

    def _write_raw(self, line: str) -> None:
        if not line.endswith("\n"):
            line += "\n"
        with self.out_lock:
            sys.stdout.write(line)
            sys.stdout.flush()

    def reply(self, rid, result: dict) -> None:
        self._write({"jsonrpc": "2.0", "id": rid, "result": result})

    def fail(self, rid, message: str) -> None:
        self._write({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": message}})

    # -- child side --------------------------------------------------------
    def _touch(self) -> None:
        self.last_activity = time.time()

    def _tail(self) -> str:
        lines = [ln.strip() for ln in list(self.stderr_tail) if ln.strip()]
        return " | ".join(lines[-3:])

    def _write_child(self, line: str) -> bool:
        if not line.endswith("\n"):
            line += "\n"
        with self.in_lock:
            proc = self.proc
            if proc is None or proc.stdin is None or proc.poll() is not None:
                return False
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except (OSError, ValueError):
                return False
        self._touch()
        return True

    def _docker_argv(self) -> list[str]:
        argv = list(self.argv)
        # shortcut: only the plain `docker run ...` shape gets a name, so an idle stop can
        # `docker rm -f` a container whose stdin EOF it ignored. Anything else is left alone.
        named = any(a == "--name" or a.startswith("--name=") for a in argv)
        if len(argv) >= 2 and os.path.basename(argv[0]) == "docker" and argv[1] == "run" and not named:
            self.spawns += 1
            self.container = f"lazy-mcp-{_slot(self.name)}-{os.getpid()}-{self.spawns}"
            argv[2:2] = ["--name", self.container]
        else:
            self.container = None
        return argv

    def _start_child(self) -> None:
        argv = self._docker_argv()
        self.stderr_tail.clear()
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise SpawnError(f"cannot start {argv[0]}: {exc}")
        with self.lock:
            self.proc = proc
        threading.Thread(target=self._read_stdout, args=(proc,), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True).start()

    def _read_stderr(self, proc) -> None:
        try:
            for line in proc.stderr:
                self.stderr_tail.append(line)
                sys.stderr.write(line)
            sys.stderr.flush()
        except (OSError, ValueError):
            pass

    def _read_stdout(self, proc) -> None:
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                self._touch()
                try:
                    msg = json.loads(line)
                except ValueError:
                    msg = None
                if not isinstance(msg, dict):
                    self._write_raw(line)
                    continue
                self._from_child(msg, line)
        except (OSError, ValueError):
            pass
        finally:
            self._child_gone(proc)

    def _from_child(self, msg: dict, line: str) -> None:
        rid = msg.get("id")
        if isinstance(rid, str) and rid.startswith(INTERNAL):
            with self.cond:
                slot = self.internal.get(rid)
                if slot is not None:
                    slot[0] = msg
                    self.cond.notify_all()
                    return
            # not ours: a client id that merely shares the prefix, forwarded below
        if "method" in msg:
            if msg.get("method") == "notifications/tools/list_changed":
                # shortcut: the real server changed under us; stop trusting the cached
                # lists so the next */list reaches it instead of replaying stale metadata
                with self.lock:
                    self.cached = None
            self._write_raw(line)
            return
        with self.lock:
            self.inflight.discard(rid)
        self._write_raw(line)

    def _child_gone(self, proc) -> None:
        with self.lock:
            if self.proc is not proc:
                return  # an intentional stop already reset the state
            self.proc = None
            self.state = "idle"
            pending = list(self.inflight)
            self.inflight.clear()
        # release the handshake (if any) with an error instead of letting it time out
        with self.cond:
            for slot in self.internal.values():
                if slot[0] is None:
                    slot[0] = {"error": {"code": -32603, "message": "MCP server exited"}}
            self.cond.notify_all()
        tail = self._tail()
        for rid in pending:
            msg = "lazy-mcp: MCP server exited before answering"
            self.fail(rid, msg + (" (" + tail + ")" if tail else ""))

    def _request(self, method: str, params, timeout: float) -> dict:
        """Internal (never forwarded) request to the child, used by the handshake."""
        with self.lock:
            self.seq += 1
            iid = INTERNAL + str(self.seq)
            slot = [None]
            self.internal[iid] = slot
        msg = {"jsonrpc": "2.0", "id": iid, "method": method}
        if params is not None:
            msg["params"] = params
        if not self._write_child(_dumps(msg)):
            with self.lock:
                self.internal.pop(iid, None)
            raise SpawnError("the MCP server is not accepting input")
        deadline = time.time() + timeout
        with self.cond:
            while slot[0] is None:
                left = deadline - time.time()
                if left <= 0 or self.closing:
                    self.internal.pop(iid, None)
                    raise SpawnError(f"timeout waiting for {method}")
                self.cond.wait(left)
        with self.lock:
            self.internal.pop(iid, None)
        resp = slot[0]
        if "error" in resp:
            err = resp["error"] or {}
            raise SpawnError(f"{method} failed: {err.get('message') or err}")
        return resp.get("result") or {}

    def _list(self, method: str, key: str) -> list:
        items, cursor = [], None
        while True:
            result = self._request(method, {"cursor": cursor} if cursor else None, LIST_TIMEOUT)
            items.extend(result.get(key) or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return items  # cached lists carry no nextCursor

    def _fetch_lists(self, initialize: dict) -> dict:
        caps = initialize.get("capabilities") or {}
        lists = {key: None for key in LIST_KEYS}
        try:
            lists["tools"] = self._list("tools/list", "tools")
        except SpawnError:
            lists["tools"] = None  # forward at runtime
        if "resources" in caps:
            for method, key in (("resources/list", "resources"),
                                ("resources/templates/list", "resourceTemplates")):
                try:
                    lists[key] = self._list(method, key)
                except SpawnError:
                    pass
        if "prompts" in caps:
            try:
                lists["prompts"] = self._list("prompts/list", "prompts")
            except SpawnError:
                pass
        return lists

    def _handshake(self, params: dict):
        self._start_child()
        initialize = self._request("initialize", copy.deepcopy(params), INIT_TIMEOUT)
        self._write_child(_dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        return initialize, self._fetch_lists(initialize)

    def _stop_child(self, reason: str = "idle") -> None:
        with self.lock:
            proc, name = self.proc, self.container
            self.proc = None
            self.state = "idle"
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=STOP_WAIT)
            return
        except subprocess.TimeoutExpired:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=KILL_WAIT)
            return
        except subprocess.TimeoutExpired:
            pass
        proc.kill()
        try:
            proc.wait(timeout=KILL_WAIT)
        except subprocess.TimeoutExpired:
            pass
        if name:
            # the docker CLI is gone but the container may still hold the stdio pipes
            subprocess.run(["docker", "rm", "-f", name], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _idle_loop(self) -> None:
        while not self.closing:
            time.sleep(POLL)
            if self.idle <= 0:
                continue
            with self.lock:
                busy = self.state != "running" or bool(self.inflight)
            if busy or time.time() - self.last_activity < self.idle:
                continue
            self._stop_child("idle")

    # -- message handling --------------------------------------------------
    def _from_cache(self, method: str):
        entry = LISTS.get(method)
        if entry is None:
            return MISS
        data = self.cached
        if data is None:
            return MISS
        items = data.get(entry[0])
        if items is None:
            return MISS  # never captured or failed: ask the real server
        return {entry[1]: copy.deepcopy(items)}

    def _initialize(self, rid, params: dict) -> None:
        self.client_params = params
        data = self.cached
        if data is not None and isinstance(data.get("initialize"), dict):
            self.reply(rid, patch_capabilities(copy.deepcopy(data["initialize"])))
            return
        with self.lock:
            self.state = "starting"
        try:
            initialize, lists = self._handshake(params)
        except SpawnError as exc:
            self._stop_child("handshake")  # a half-initialized child must not linger
            tail = self._tail()
            self.fail(rid, f"lazy-mcp: cannot start the MCP server: {exc}{tail_of(tail)}")
            return
        self._remember(initialize, lists)
        with self.lock:
            self.state = "running" if self.proc is not None else "idle"
        self.reply(rid, patch_capabilities(copy.deepcopy(initialize)))

    def _remember(self, initialize: dict, lists: dict) -> bool:
        """Cache the handshake result; True when it moved away from an existing cache."""
        data = self.cache.build(initialize, lists)
        with self.lock:
            before = self.cached
            self.cached = data
        changed = before is not None and any(before.get(k) != lists.get(k) for k in LIST_KEYS)
        try:
            self.cache.save(data)
        except OSError as exc:
            sys.stderr.write(f"lazy-mcp: cannot write cache: {exc}\n")
        return changed

    def _spawn_then_flush(self) -> None:
        params = self.client_params
        if not isinstance(params, dict):
            params = {"protocolVersion": "2024-11-05", "capabilities": {},
                      "clientInfo": {"name": "lazy-mcp", "version": "1"}}
        try:
            initialize, lists = self._handshake(params)
        except SpawnError as exc:
            with self.lock:
                queued, self.queue = self.queue, []
            self._stop_child("handshake")  # a half-initialized child must not linger
            tail = self._tail()
            message = f"lazy-mcp: cannot start the MCP server: {exc}{tail_of(tail)}"
            for msg, _ in queued:
                if msg.get("id") is not None:
                    self.fail(msg["id"], message)
            return
        changed = self._remember(initialize, lists)
        if changed:
            self._write({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        # stay "starting" until the queue is empty, so nothing enqueued meanwhile is stranded
        while True:
            with self.lock:
                queued, self.queue = self.queue, []
                if not queued:
                    self.state = "running" if self.proc is not None else "idle"
                    return
            for msg, raw in queued:
                self._deliver(msg, raw)

    def _deliver(self, msg: dict, raw: str) -> None:
        """Send a client request to the child, tracked so its death cannot lose the answer."""
        rid = msg.get("id")
        if rid is not None:
            with self.lock:
                self.inflight.add(rid)
        if self._write_child(raw) or rid is None:
            return
        with self.lock:
            mine = rid in self.inflight  # the reader may have answered it already
            self.inflight.discard(rid)
        if mine:
            self.fail(rid, "lazy-mcp: the MCP server is not available")

    def _enqueue(self, msg: dict, raw: str, start: bool) -> None:
        """Queue for a spawn in flight, or deliver if the flush finished meanwhile.

        The caller's state check races with `_spawn_then_flush` draining the queue and
        flipping to "running", so it is re-checked under the lock here: queueing after
        that point would leave the request without an answer forever.
        """
        with self.lock:
            deliver = self.state == "running"
            if not deliver:
                self.queue.append((msg, raw))
                if start:
                    self.state = "starting"
        if deliver:
            self._deliver(msg, raw)
        elif start:
            threading.Thread(target=self._spawn_then_flush, daemon=True).start()

    def _forward(self, msg: dict, raw: str) -> None:
        with self.lock:
            state = self.state
        if state == "running":
            self._deliver(msg, raw)
            return
        self._enqueue(msg, raw, start=state == "idle")

    def _notification(self, msg: dict, raw: str) -> None:
        method = msg.get("method")
        if method == "notifications/initialized":
            return  # the handshake already sent ours
        if method == "notifications/cancelled":
            rid = (msg.get("params") or {}).get("requestId")
            with self.lock:
                queued = [q for q in self.queue if q[0].get("id") != rid]
                self.queue = queued
        if not self._write_child(raw) and method != "notifications/cancelled":
            return  # child down: nothing to tell it, and we must not spawn for a notification

    def handle(self, msg: dict, raw: str) -> None:
        self._touch()
        method = msg.get("method")
        rid = msg.get("id")
        if method is None:
            self._write_child(raw)  # a client response to a server->client request
            return
        if rid is None:
            self._notification(msg, raw)
            return
        if method == "ping":
            self.reply(rid, {})
            return
        if method == "initialize":
            self._initialize(rid, msg.get("params") or {})
            return
        cached = self._from_cache(method)
        if cached is not MISS:
            self.reply(rid, cached)
            return
        self._forward(msg, raw)

    # -- entry points ------------------------------------------------------
    def serve(self) -> None:
        threading.Thread(target=self._idle_loop, daemon=True).start()
        try:
            for raw in sys.stdin:
                raw = raw.rstrip("\n")
                if not raw.strip():
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                try:
                    self.handle(msg, raw)
                except Exception as exc:  # noqa: BLE001 - one bad message must not end the session
                    sys.stderr.write(f"lazy-mcp: {exc}\n")
        except (OSError, KeyboardInterrupt):
            pass
        finally:
            self.shutdown(0)

    def refresh(self) -> int:
        params = {"protocolVersion": "2024-11-05", "capabilities": {},
                  "clientInfo": {"name": "lazy-mcp", "version": "1"}}
        try:
            initialize, lists = self._handshake(params)
        except SpawnError as exc:
            tail = self._tail()
            sys.stderr.write(f"lazy-mcp: refresh failed: {exc}{tail_of(tail)}\n")
            self._stop_child("refresh")
            return 1
        self._remember(initialize, lists)
        self._stop_child("refresh")
        sys.stderr.write(
            f"lazy-mcp: cached {len(lists.get('tools') or [])} tools for {self.name}"
            f" in {self.cache.path}\n"
        )
        return 0

    def shutdown(self, code: int = 0) -> None:
        self.closing = True
        self._stop_child("shutdown")
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        os._exit(code)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="lazy-mcp.py",
        description="Serve an MCP server's metadata from a cache and spawn the real "
                    "server (docker run) only on first use.",
        epilog="Example: lazy-mcp.py --name whatsapp --refresh -- docker run -i --rm image:0.2.0",
    )
    parser.add_argument("--name", required=True,
                        help="cache key, normally the mcpServers entry name")
    parser.add_argument("--refresh", action="store_true",
                        help="spawn once, rewrite the cache and exit")
    if "--" in argv:
        split = argv.index("--")
        head, cmd = argv[:split], argv[split + 1:]
    else:
        head, cmd = argv, []
    args = parser.parse_args(head)
    if not cmd:
        parser.error("missing `-- CMD...`: the real MCP server command goes after `--`")
    args.argv = cmd
    return args


def main(argv) -> int:
    args = parse_args(argv)
    shim = Shim(args.name, args.argv)
    if args.refresh:
        return shim.refresh()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        # shortcut: hard exit from the handler, so a stop never waits on a blocked stdin read
        signal.signal(sig, lambda *_: shim.shutdown(0))
    shim.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
