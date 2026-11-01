#!/usr/bin/env python3
"""Keep MCP server, skill, plugin and package versions linked. No manual tagging.

  release.py amend   post-commit: bump what HEAD touched (level from its Conventional Commit message:
                     feat = minor, `!`/BREAKING CHANGE = major, else patch), rewrite every derived
                     file and amend HEAD with them (no git hook can edit the commit being made,
                     and only post-commit sees the final message)
  release.py sync    same bump from the staged changes, patch level, no amend (manual use)
  release.py check   CI: fail if any derived file is stale (no writes)

Source of truth: servers/*/pyproject.toml `version` (MCP) and skills/*/SKILL.md `metadata.version` (skill).
Derived: plugin.json image pins, skill `requires-mcp` (server major.minor), plugin/marketplace/package
versions, pi-mcp.json (for Pi), and the image tags in .woodpecker/build.yaml (CI publishes on push to master).
"""
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ".claude-plugin/plugin.json"
MARKET = ".claude-plugin/marketplace.json"
PACKAGE = "package.json"
PI_MCP = "pi-mcp.json"
BUILD = ".woodpecker/build.yaml"
PLUGIN_PREFIXES = ("skills/", "servers/", "agents/", "commands/", "hooks/")
VERSION = re.compile(r'^version = "(\d+\.\d+\.\d+)"', re.M)
JSON_VERSION = re.compile(r'^(  "version": ")[^"]+(")', re.M)


def level(msg: str) -> str:
    """Conventional Commits -> semver level."""
    subject = msg.strip().split("\n", 1)[0]
    if re.match(r"^\w+(\([^)]*\))?!:", subject) or re.search(r"^BREAKING[ -]CHANGE:", msg, re.M):
        return "major"
    return "minor" if re.match(r"^feat(\([^)]*\))?:", subject) else "patch"


def bump(v: str, lvl: str = "patch") -> str:
    a, b, c = (int(x) for x in v.split("."))
    return {"major": f"{a + 1}.0.0", "minor": f"{a}.{b + 1}.0", "patch": f"{a}.{b}.{c + 1}"}[lvl]


def bumped(cur: str, old: str | None, touched: bool, lvl: str = "patch") -> str:
    """Bump `cur` once: only if its files changed and the version is not already ahead of HEAD."""
    return bump(cur, lvl) if touched and cur == old else cur


def frontmatter_set(text: str, key: str, value: str) -> str:
    """Set `metadata.<key>` in a SKILL.md frontmatter, creating the `metadata:` block if needed."""
    end = text.index("\n---", 4)
    fm, rest = text[:end], text[end:]
    line = f'  {key}: "{value}"'
    if re.search(rf"^  {key}: .*$", fm, re.M):
        fm = re.sub(rf"^  {key}: .*$", line, fm, flags=re.M)
    elif re.search(r"^metadata:\s*$", fm, re.M):
        fm = re.sub(r"^(metadata:\s*)$", rf"\1\n{line}", fm, count=1, flags=re.M)
    else:
        fm += f"\nmetadata:\n{line}"
    return fm + rest


def frontmatter_get(text: str, key: str) -> str | None:
    m = re.search(rf'^  {key}: "?([^"\n]+)"?$', text[: text.index("\n---", 4)], re.M)
    return m.group(1) if m else None


def quote(arg: str) -> str:
    return f'"{arg}"' if "${" in arg else shlex.quote(arg)


def pi_mcp(plugin: dict) -> dict:
    """Pi's adapter does not expand ${HOME}/${PWD} in args, so run docker through `sh -c`."""
    servers = {}
    for name, e in plugin["mcpServers"].items():
        cmd = " ".join(quote(str(a)) for a in [e["command"], *e.get("args", [])])
        servers[name] = {"command": "sh", "args": ["-c", f"exec {cmd}"]}
    return {"mcpServers": servers}


def plan(root: Path, changed: set[str] | None, head: Callable[[str], str], lvl: str = "patch") -> dict[str, str]:
    """Desired content of every derived/bumped file. `changed` None = no bumps (check mode)."""
    files: dict[str, str] = {}
    changed = changed or set()
    # tests and docs ship in no image/skill behaviour: they must not cut a new version
    real = {c for c in changed if "/tests/" not in c and not c.endswith(".md") or c.endswith("SKILL.md")}
    touched = lambda prefix: any(c.startswith(prefix) for c in real)  # noqa: E731

    # 1. MCP servers: name -> (relative pyproject, version)
    servers: dict[str, str] = {}
    for py in sorted(root.glob("servers/*/pyproject.toml")):
        rel = py.relative_to(root).as_posix()
        text = py.read_text()
        name = re.search(r'^name = "([^"]+)"', text, re.M)[1]
        cur = VERSION.search(text)[1]
        old = VERSION.search(head(rel))
        new = bumped(cur, old and old[1], touched(rel.rsplit("/", 1)[0] + "/"), lvl)
        if new != cur:
            files[rel] = VERSION.sub(f'version = "{new}"', text, count=1)
        servers[name] = new

    # 2. skills: own version (bumped when the skill changes) + requires-mcp = server major.minor
    skills_changed = False
    for md in sorted(root.glob("skills/*/SKILL.md")):
        rel = md.relative_to(root).as_posix()
        text = md.read_text()
        old = frontmatter_get(head(rel), "version") if head(rel) else None
        cur = frontmatter_get(text, "version") or "0.1.0"
        new = bumped(cur, old, touched(rel.rsplit("/", 1)[0] + "/"), lvl)
        out = frontmatter_set(text, "version", new)
        req = re.search(r'requires-mcp: "([\w-]+) \d+\.\d+"', out)
        if req and req[1] in servers:
            mm = ".".join(servers[req[1]].split(".")[:2])
            out = out.replace(req[0], f'requires-mcp: "{req[1]} {mm}"')
        if out != text:
            files[rel] = out
        skills_changed |= new != cur

    # 3. plugin.json: pin every first-party image to its server version
    text = (root / PLUGIN).read_text()
    for name, ver in servers.items():
        text = re.sub(rf"(harbor\.bzd\.gg/bzd/{re.escape(name)}):[\w.\-]+", rf"\1:{ver}", text)
    cur_v = re.search(r'"version": "([^"]+)"', text)[1]
    old = re.search(r'"version": "([^"]+)"', head(PLUGIN))
    dirty = skills_changed or bool(files) or any(c.startswith(PLUGIN_PREFIXES) for c in real)
    plugin_v = bumped(cur_v, old and old[1], dirty, lvl)
    text = JSON_VERSION.sub(rf"\g<1>{plugin_v}\2", text, count=1)
    files[PLUGIN] = text

    # 4. same version in marketplace.json and package.json; pi-mcp.json and CI image tags follow
    for rel in (MARKET, PACKAGE):
        files[rel] = JSON_VERSION.sub(rf"\g<1>{plugin_v}\2", (root / rel).read_text(), count=1)
    files[PI_MCP] = json.dumps(pi_mcp(json.loads(text)), indent=2) + "\n"

    build = (root / BUILD).read_text()

    def tags(m: re.Match) -> str:
        ver = servers.get(m[2])
        return m[0] if ver is None else f'{m[1]}[latest, "sha-${{CI_COMMIT_SHA}}", "{ver}"]'

    files[BUILD] = re.sub(
        r"(repo: harbor\.bzd\.gg/bzd/([\w-]+)\n(?:(?!\n  - name).)*?tags: )\[[^\]]*\]", tags, build, flags=re.S
    )
    return files


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "sync"
    if mode not in ("sync", "check", "amend"):
        print(__doc__)
        return 2
    amend = mode == "amend"
    lvl = level(_git("log", "-1", "--format=%B")) if amend else "patch"
    changed = None
    if mode == "sync":
        changed = set(_git("diff", "--cached", "--name-only", "--diff-filter=ACMR").split())
    elif amend:
        changed = set(_git("diff-tree", "--no-commit-id", "--name-only", "-r", "--diff-filter=ACMR", "HEAD").split())
    ref = "HEAD~1" if amend else "HEAD"
    # check mode never bumps, so it needs no git (CI's python:slim image has none)
    files = plan(ROOT, changed, (lambda p: "") if mode == "check" else lambda p: _git("show", f"{ref}:{p}"), lvl)
    stale = [rel for rel, new in files.items() if not (ROOT / rel).exists() or (ROOT / rel).read_text() != new]
    if mode == "check":
        for rel in stale:
            print(f"stale: {rel} (run scripts/release.py sync)")
        return 1 if stale else 0
    for rel in stale:
        (ROOT / rel).write_text(files[rel])
    if stale:
        _git("add", *stale)
        print("release.py updated:", ", ".join(stale))
        if amend:
            _git("commit", "--amend", "--no-verify", "--no-edit")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
