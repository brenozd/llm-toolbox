#!/usr/bin/env python3
"""Tests for scripts/lazy-mcp.py. Stdlib only: `python3 scripts/test_lazy_mcp.py`.

The shim runs as a real subprocess and is driven over stdio. `docker` on PATH is a
throwaway wrapper that execs this same file in `--fake-child` mode: a tiny MCP
server that appends one line per start to a counter file (so a test can assert how
many containers were really started) and whose behaviour is switched by a flag file
(die mid-call, exit on start, changed tool list).
"""
import json
import os
import pathlib
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SHIM = HERE / "lazy-mcp.py"
IMAGE = "harbor.bzd.gg/bzd/demo-mcp"
TOOLS = [
    {"name": "echo", "description": "echo", "inputSchema": {"type": "object"}},
    {"name": "sleep", "description": "sleep", "inputSchema": {"type": "object"}},
    {"name": "die", "description": "die", "inputSchema": {"type": "object"}},
]
TOOLS_V2 = TOOLS + [
    {"name": "added", "description": "later", "inputSchema": {"type": "object"}},
]


def _write(msg):
    sys.stdout.write(json.dumps(msg, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _note(text):
    path = os.environ.get("FAKE_NOTES")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def fake_child() -> int:
    """Minimal MCP server: just enough to exercise the shim."""
    counter = os.environ.get("FAKE_COUNTER")
    if counter:
        with open(counter, "a", encoding="utf-8") as fh:
            fh.write(f"start {os.getpid()}\n")
    flags = os.environ.get("FAKE_FLAGS")
    mode = ""
    if flags and os.path.exists(flags):
        with open(flags, encoding="utf-8") as fh:
            mode = fh.read().strip()
    if mode == "exit-on-start":
        return 3
    tools = TOOLS_V2 if mode == "tools-v2" else TOOLS
    sleep_for = float(os.environ.get("FAKE_SLEEP") or 0)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method, rid = msg.get("method"), msg.get("id")
        if method is None:
            continue
        if rid is None:
            _note(f"{method} {json.dumps(msg.get('params'))}")
            continue
        if method == "initialize":
            params = msg.get("params") or {}
            result = {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {"listChanged": False}, "resources": {},
                                 "prompts": {}},
                "serverInfo": {"name": "fake", "version": "1.0.0"},
            }
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "resources/list":
            result = {"resources": [{"uri": "file:///one", "name": "one"}]}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": [{"uriTemplate": "file:///{x}", "name": "t"}]}
        elif method == "prompts/list":
            result = {"prompts": [{"name": "p"}]}
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name == "die" and mode == "die-mid-call":
                sys.stdout.flush()
                os._exit(4)  # die with the request in flight, no answer
            if name == "sleep":
                time.sleep(sleep_for)
            result = {"content": [{"type": "text", "text": f"{name} done"}]}
        else:
            _write({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": "no such method"}})
            continue
        _write({"jsonrpc": "2.0", "id": rid, "result": result})
    return 0


class Harness:
    """One shim process talking MCP over pipes to the fake child."""

    def __init__(self, tmp: pathlib.Path, image: str = f"{IMAGE}:1.0",
                 idle=None, env=None) -> None:
        self.tmp = tmp
        self.image = image
        self.idle = idle
        self.extra_env = env or {}
        self.cache_dir = tmp / "cache"
        self.counter = tmp / "counter"
        self.flags = tmp / "flags"
        self.notes = tmp / "notes"
        self.stderr = []
        self.seen = []
        self.proc = None
        self._inbox = queue.Queue()
        self._make_docker()

    def _make_docker(self) -> None:
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        wrapper = bin_dir / "docker"
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'rm':\n"
            "    sys.exit(0)\n"
            f"os.execv(sys.executable, [sys.executable, {str(pathlib.Path(__file__))!r},"
            " '--fake-child'])\n"
        )
        wrapper.chmod(0o755)

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("LAZY_MCP_")}
        env["PATH"] = f"{self.tmp / 'bin'}{os.pathsep}{env.get('PATH', '')}"
        env["LAZY_MCP_CACHE_DIR"] = str(self.cache_dir)
        env["FAKE_COUNTER"] = str(self.counter)
        env["FAKE_FLAGS"] = str(self.flags)
        env["FAKE_NOTES"] = str(self.notes)
        if self.idle is not None:
            env["LAZY_MCP_IDLE_SECONDS"] = str(self.idle)
        env.update({k: str(v) for k, v in self.extra_env.items()})
        return env

    def start(self, refresh: bool = False) -> "Harness":
        args = [sys.executable, "-I", str(SHIM), "--name", "demo"]
        if refresh:
            args.append("--refresh")
        args += ["--", "docker", "run", "-i", "--rm", self.image]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1,
                                     env=self.env())
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        return self

    def _read_out(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._inbox.put(json.loads(line))
            except ValueError:
                continue

    def _read_err(self) -> None:
        for line in self.proc.stderr:
            self.stderr.append(line)

    def send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def wait(self, rid, timeout: float = 25.0) -> dict:
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise AssertionError(f"timeout waiting for id={rid!r}; stderr={self.stderr}")
            try:
                msg = self._inbox.get(timeout=left)
            except queue.Empty:
                raise AssertionError(f"timeout waiting for id={rid!r}; stderr={self.stderr}")
            if msg.get("id") == rid and "method" not in msg:
                return msg
            self.seen.append(msg)

    def request(self, rid, method: str, params=None, timeout: float = 25.0) -> dict:
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        return self.wait(rid, timeout)

    def initialize(self, rid=1) -> dict:
        res = self.request(rid, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res

    def call(self, rid, name: str, timeout: float = 25.0) -> dict:
        return self.request(rid, "tools/call", {"name": name, "arguments": {}}, timeout)

    def set_mode(self, mode: str) -> None:
        self.flags.write_text(mode, encoding="utf-8")

    def notifications(self, method="notifications/tools/list_changed") -> list:
        return [m for m in self.seen if m.get("method") == method]

    def note_lines(self) -> list:
        try:
            return self.notes.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

    def starts(self) -> int:
        try:
            return len(self.counter.read_text(encoding="utf-8").splitlines())
        except OSError:
            return 0

    def pids(self) -> list:
        try:
            lines = self.counter.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [int(ln.split()[1]) for ln in lines if ln.startswith("start ")]

    def cache_files(self) -> list:
        return sorted(self.cache_dir.glob("*.json")) if self.cache_dir.exists() else []

    def stop(self, timeout: float = 25.0):
        if self.proc is None:
            return None
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        code = self.proc.wait(timeout=timeout)
        self._close_pipes()
        return code

    def _close_pipes(self) -> None:
        for pipe in (self.proc.stdout, self.proc.stderr, self.proc.stdin):
            try:
                if pipe is not None:
                    pipe.close()
            except OSError:
                pass
        self.proc = None

    def kill(self) -> None:
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait(timeout=10)
            self._close_pipes()

    def refresh(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(SHIM), "--name", "demo", "--refresh",
             "--", "docker", "run", "-i", "--rm", self.image],
            capture_output=True, text=True, timeout=60, check=False, env=self.env(),
        )


def wait_until(predicate, timeout: float = 10.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class LazyShimTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lazy-mcp-test-")
        self.tmp = pathlib.Path(self._tmp.name)
        self.harnesses = []

    def tearDown(self) -> None:
        for harness in self.harnesses:
            try:
                harness.kill()
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._tmp.cleanup()

    def shim(self, **kwargs) -> Harness:
        harness = Harness(self.tmp, **kwargs)
        self.harnesses.append(harness)
        return harness

    def cold(self, **kwargs) -> Harness:
        """One full cold session: spawn, write the cache, exit."""
        harness = self.shim(**kwargs).start()
        self.assertIn("result", harness.initialize())
        self.assertEqual(harness.stop(), 0)
        return harness

    def warm(self, **kwargs) -> Harness:
        """The cache of a cold session, then a fresh shim that has not spawned yet."""
        self.cold(**kwargs)
        return self.shim(**kwargs).start()

    def test_cold_start_writes_cache(self) -> None:
        harness = self.shim().start()
        self.assertIn("result", harness.initialize())
        self.assertEqual(harness.starts(), 1)
        files = wait_until(harness.cache_files) or []
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, "demo-1.0.json")
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["name"], "demo")
        self.assertEqual(data["image"], f"{IMAGE}:1.0")
        self.assertEqual([t["name"] for t in data["tools"]],
                         [t["name"] for t in TOOLS])
        self.assertEqual(data["resources"][0]["uri"], "file:///one")
        self.assertEqual(data["prompts"], [{"name": "p"}])
        self.assertNotIn("nextCursor", data["tools"])
        self.assertEqual(harness.stop(), 0)

    def test_warm_start_answers_without_spawning(self) -> None:
        first = self.cold()
        before = first.starts()
        harness = self.shim().start()
        init = harness.initialize()
        self.assertEqual(init["result"]["serverInfo"]["name"], "fake")
        self.assertTrue(init["result"]["capabilities"]["tools"]["listChanged"])
        listed = harness.request(2, "tools/list")
        self.assertEqual([t["name"] for t in listed["result"]["tools"]],
                         [t["name"] for t in TOOLS])
        self.assertEqual(harness.request(3, "ping")["result"], {})
        self.assertEqual(harness.request(4, "resources/list")["result"]["resources"][0]["name"],
                         "one")
        self.assertEqual(harness.starts(), before)
        self.assertEqual(harness.stop(), 0)

    def test_tool_call_spawns_once_and_keeps_ids(self) -> None:
        harness = self.warm()
        before = harness.starts()
        harness.initialize()
        self.assertEqual(harness.starts(), before)
        first = harness.call(7, "echo")
        self.assertEqual(first["id"], 7)
        self.assertEqual(first["result"]["content"][0]["text"], "echo done")
        second = harness.call("abc", "echo")
        self.assertEqual(second["id"], "abc")
        self.assertEqual(harness.starts(), before + 1)
        self.assertEqual(harness.stop(), 0)

    def test_concurrent_calls_share_one_spawn(self) -> None:
        harness = self.warm(env={"FAKE_SLEEP": "0.2"})
        before = harness.starts()
        harness.initialize()
        for rid in range(1, 6):
            harness.send({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                          "params": {"name": "sleep", "arguments": {}}})
        for rid in range(1, 6):
            self.assertEqual(harness.wait(rid)["id"], rid)
        self.assertEqual(harness.starts(), before + 1)
        self.assertEqual(harness.stop(), 0)

    def test_idle_stop_then_respawn(self) -> None:
        harness = self.warm(idle=1)
        before = harness.starts()
        harness.initialize()
        harness.call(2, "echo")
        self.assertEqual(harness.starts(), before + 1)
        pid = harness.pids()[-1]
        self.assertTrue(alive(pid))
        self.assertIsNotNone(wait_until(lambda: not alive(pid), timeout=8))
        harness.call(3, "echo")
        self.assertEqual(harness.starts(), before + 2)
        self.assertEqual(harness.stop(), 0)

    def test_inflight_call_survives_idle_stop(self) -> None:
        harness = self.warm(idle=1, env={"FAKE_SLEEP": "2"})
        harness.initialize()
        harness.send({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                      "params": {"name": "sleep", "arguments": {}}})
        time.sleep(1.5)
        pid = harness.pids()[-1]
        self.assertTrue(alive(pid), "the idle watcher killed an in-flight call")
        self.assertEqual(harness.wait(9)["result"]["content"][0]["text"], "sleep done")
        self.assertEqual(harness.stop(), 0)

    def test_mid_call_death_errors_id_then_recovers(self) -> None:
        harness = self.warm()
        harness.set_mode("die-mid-call")
        harness.initialize()
        died = harness.call(4, "die")
        self.assertIn("error", died)
        self.assertEqual(died["id"], 4)
        self.assertIn("exited", died["error"]["message"])
        harness.set_mode("")
        self.assertEqual(harness.call(5, "echo")["result"]["content"][0]["text"], "echo done")
        self.assertEqual(harness.stop(), 0)

    def test_failing_start_errors_then_recovers(self) -> None:
        harness = self.shim()
        harness.set_mode("exit-on-start")
        harness.start()
        failed = harness.initialize()
        self.assertIn("error", failed)
        self.assertEqual(failed["error"]["code"], -32603)
        harness.set_mode("")
        self.assertEqual(harness.call(2, "echo")["result"]["content"][0]["text"], "echo done")
        self.assertEqual(harness.stop(), 0)

    def test_stdin_eof_stops_shim_and_child(self) -> None:
        harness = self.shim().start()
        harness.initialize()
        pid = harness.pids()[-1]
        self.assertEqual(harness.stop(), 0)
        self.assertIsNotNone(wait_until(lambda: not alive(pid), timeout=8))

    def test_image_tag_picks_cache_file(self) -> None:
        self.cold()
        self.assertEqual([p.name for p in self.shim().cache_files()], ["demo-1.0.json"])
        self.cold(image=f"{IMAGE}:2.0")
        names = [p.name for p in self.shim().cache_files()]
        self.assertEqual(names, ["demo-2.0.json"])

    def test_changed_tools_notify_and_rewrite_cache(self) -> None:
        harness = self.warm()
        harness.set_mode("tools-v2")
        harness.initialize()
        harness.call(2, "echo")
        self.assertTrue(wait_until(lambda: harness.notifications(), timeout=10),
                        "no notifications/tools/list_changed")
        files = harness.cache_files()
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertIn("added", [t["name"] for t in data["tools"]])
        self.assertEqual(harness.stop(), 0)

    def test_cancelled_notification_forwarded(self) -> None:
        harness = self.warm()
        harness.initialize()
        harness.call(2, "echo")  # the child is up now
        harness.send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                      "params": {"requestId": 99, "reason": "test"}})
        found = wait_until(
            lambda: [ln for ln in harness.note_lines()
                     if ln.startswith("notifications/cancelled") and "99" in ln],
            timeout=10)
        self.assertTrue(found, f"cancelled never reached the child: {harness.note_lines()}")
        self.assertEqual(harness.stop(), 0)

    def test_cache_permissions(self) -> None:
        self.cold()
        cache = self.shim().cache_files()[0]
        self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
        self.assertEqual(cache.parent.stat().st_mode & 0o777, 0o700)

    def test_refresh_fills_cache_without_a_client(self) -> None:
        harness = self.shim()
        out = harness.refresh()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "")
        files = harness.cache_files()
        self.assertEqual([p.name for p in files], ["demo-1.0.json"])
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual([t["name"] for t in data["tools"]], [t["name"] for t in TOOLS])
        self.assertEqual(harness.starts(), 1)
        pid = harness.pids()[-1]
        self.assertIsNotNone(wait_until(lambda: not alive(pid), timeout=8))

    def test_help_exits_zero(self) -> None:
        out = subprocess.run([sys.executable, "-I", str(SHIM), "--help"],
                             capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0)
        self.assertIn("--name", out.stdout)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fake-child":
        sys.exit(fake_child())
    unittest.main(verbosity=2)
