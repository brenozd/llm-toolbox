#!/usr/bin/env python3
"""Tests for validate-plugin.py: the `-exec` MCP entry invariant (M7).

An `-exec` entry must be the same image as its base entry and differ only by
`-e PROMO_ALLOW_EXEC=1` + `--network none` (plus the documented SETGID/add-host
split). Run with `python3 -m pytest scripts/test_validate_plugin.py` or
`python3 scripts/test_validate_plugin.py`.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("validate-plugin.py")
IMAGE = "harbor.bzd.gg/bzd/promo-video-mcp:latest"

BASE_ARGS = [
    "run", "-i", "--rm", "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges", "--read-only",
    "--tmpfs", "/tmp:rw,exec", "--tmpfs", "/root", "--pids-limit", "256",
    "--add-host=host.docker.internal:host-gateway",
    "-v", "${PWD}:/repo:ro", "-v", "promo-video-work:/work",
    "-v", "${HOME}/.cache/promo-video/music:/music:ro",
    IMAGE,
]

EXEC_ARGS = [
    "run", "-i", "--rm", "--network", "none", "--cap-drop", "ALL",
    "--cap-add", "SETGID",
    "--security-opt", "no-new-privileges", "--read-only",
    "--tmpfs", "/tmp:rw,exec", "--pids-limit", "256", "--tmpfs", "/root",
    "-e", "PROMO_ALLOW_EXEC=1",
    "-v", "${PWD}:/repo:ro", "-v", "promo-video-work:/work",
    "-v", "${HOME}/.cache/promo-video/music:/music:ro",
    IMAGE,
]


def load_module():
    spec = importlib.util.spec_from_file_location("validate_plugin", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReferencesTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".claude-plugin").mkdir()
        (self.root / "servers").mkdir()
        self.marketplace = self.root / ".claude-plugin" / "marketplace.json"
        self.marketplace.write_text("{}")

    def check(self, mcp_servers, server_dirs=("promo-video",)):
        """Build a tmp tree and run check_references on it."""
        for name in server_dirs:
            (self.root / "servers" / name).mkdir(exist_ok=True)
        plugin = {
            "name": "test",
            "description": "",
            "mcpServers": {
                name: {"command": "docker", "args": list(args)}
                for name, args in mcp_servers.items()
            },
        }
        plugin_json = self.root / ".claude-plugin" / "plugin.json"
        plugin_json.write_text(json.dumps(plugin))
        return self.mod.check_references(plugin_json, self.marketplace)

    @staticmethod
    def failures(messages):
        return [m for m in messages if "✗" in m]

    # --- good cases -------------------------------------------------------

    def test_good_exec_pair_passes(self):
        messages = self.check({
            "promo-video": BASE_ARGS,
            "promo-video-exec": EXEC_ARGS,
        })
        self.assertEqual(self.failures(messages), [])
        self.assertIn("  ✓ MCP server 'promo-video-exec' exists", messages)

    def test_joined_flag_form_also_accepted(self):
        exec_args = list(EXEC_ARGS)
        i = exec_args.index("--network")
        exec_args[i:i + 2] = ["--network=none"]
        messages = self.check({"promo-video": BASE_ARGS, "promo-video-exec": exec_args})
        self.assertEqual(self.failures(messages), [])

    def test_plain_entry_passes(self):
        messages = self.check({"promo-video": BASE_ARGS})
        self.assertEqual(self.failures(messages), [])

    # --- bad cases -------------------------------------------------------

    def test_exec_twin_with_other_image_fails(self):
        exec_args = list(EXEC_ARGS)
        exec_args[-1] = "harbor.bzd.gg/bzd/other-mcp:latest"
        messages = self.check({"promo-video": BASE_ARGS, "promo-video-exec": exec_args})
        self.assertTrue(any("image" in m and "✗" in m for m in messages), messages)

    def test_exec_twin_without_allow_exec_fails(self):
        exec_args = list(EXEC_ARGS)
        i = exec_args.index("-e")
        del exec_args[i:i + 2]
        messages = self.check({"promo-video": BASE_ARGS, "promo-video-exec": exec_args})
        self.assertTrue(any("PROMO_ALLOW_EXEC" in m and "✗" in m for m in messages), messages)

    def test_exec_twin_without_network_none_fails(self):
        exec_args = list(EXEC_ARGS)
        i = exec_args.index("--network")
        del exec_args[i:i + 2]
        messages = self.check({"promo-video": BASE_ARGS, "promo-video-exec": exec_args})
        self.assertTrue(any("--network none" in m and "✗" in m for m in messages), messages)

    def test_exec_entry_without_base_entry_fails(self):
        messages = self.check({"promo-video-exec": EXEC_ARGS}, server_dirs=("promo-video",))
        self.assertTrue(any("no base entry" in m for m in messages), messages)

    def test_exec_twin_with_extra_flag_fails(self):
        exec_args = list(EXEC_ARGS)
        exec_args.insert(exec_args.index("--rm") + 1, "--privileged")
        messages = self.check({"promo-video": BASE_ARGS, "promo-video-exec": exec_args})
        self.assertTrue(any("drift" in m for m in messages), messages)

    def test_exec_twin_missing_base_flag_fails(self):
        exec_args = [a for a in EXEC_ARGS if a != "256"]
        messages = self.check({"promo-video": BASE_ARGS, "promo-video-exec": exec_args})
        self.assertTrue(any("drift" in m for m in messages), messages)

    def test_base_entry_setting_allow_exec_fails(self):
        base_args = list(BASE_ARGS)
        base_args[-1:-1] = ["-e", "PROMO_ALLOW_EXEC=1"]
        messages = self.check({"promo-video": base_args})
        self.assertTrue(any("must not set PROMO_ALLOW_EXEC" in m for m in messages), messages)

    def test_exec_twin_needs_its_server_directory(self):
        messages = self.check(
            {"promo-video": BASE_ARGS, "promo-video-exec": EXEC_ARGS}, server_dirs=()
        )
        self.assertTrue(any("not found in servers/" in m for m in messages), messages)


class RepoTreeTest(unittest.TestCase):
    def test_repo_plugin_json_passes(self):
        """The invariant holds for the real tree (guards against drift)."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ALL CHECKS PASSED", result.stdout)


if __name__ == "__main__":
    unittest.main()
