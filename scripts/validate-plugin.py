#!/usr/bin/env python3
"""Validate plugin structure: SKILL.md frontmatter, JSON config, and disk references."""

import json
import re
import sys
from pathlib import Path

# A `-exec` entry is the same image as its base entry, only allowed to run
# commands: it sets STORYBOARD_ALLOW_EXEC=1 and drops the network.
EXEC_SUFFIX = "-exec"
EXEC_FLAG = ("-e", "STORYBOARD_ALLOW_EXEC=1")
EXEC_NETWORK = ("--network", "none")
# The only other args allowed to differ between an entry and its `-exec` twin:
# the base has network (add-host) and the exec twin needs SETGID to drop privs.
EXEC_ONLY_ARGS = (EXEC_FLAG, EXEC_NETWORK, ("--cap-add", "SETGID"))
BASE_ONLY_ARGS = (("--add-host=host.docker.internal:host-gateway",),)
# An entry may be wrapped in the lazy shim (scripts/lazy-mcp.py --name <key> -- docker run ...).
# Everything after `--` is the real command; checks below run on that, not on the wrapper.
SHIM_SUFFIX = "lazy-mcp.py"
PLUGIN_ROOT_VARS = ("${CLAUDE_PLUGIN_ROOT}", "$CLAUDE_PLUGIN_ROOT")


def real_argv(entry: dict) -> list[str]:
    """The command line that actually runs: what follows `--` if present, else [command, *args]."""
    args = [str(a) for a in entry.get("args", [])]
    if "--" in args:
        return args[args.index("--") + 1:]
    return [str(entry.get("command", "")), *args]


def _shim_parts(entry: dict) -> tuple[list[str], list[str]] | None:
    """(args before `--`, args after it) when the entry runs the lazy shim, else None."""
    args = [str(a) for a in entry.get("args", [])]
    tokens = [str(entry.get("command", "")), *args]
    if not any(t.endswith(SHIM_SUFFIX) for t in tokens):
        return None
    if "--" not in args:
        return args, []
    return args[:args.index("--")], args[args.index("--") + 1:]


def check_shim_entry(name: str, entry: dict, root: Path) -> list[str]:
    """A shim entry must name the entry key, keep `--`, and point at a script that exists."""
    parts = _shim_parts(entry)
    if parts is None:
        return []
    head, tail = parts
    errors = []
    if "--" not in [str(a) for a in entry.get("args", [])]:
        errors.append(f"  ✗ MCP server '{name}' shim has no '--' before the command it wraps")
    at = head.index("--name") if "--name" in head else None
    given = head[at + 1] if at is not None and at + 1 < len(head) else None
    if given != name:
        errors.append(f"  ✗ MCP server '{name}' shim must pass '--name {name}' (got {given!r})")
    if not tail:
        errors.append(f"  ✗ MCP server '{name}' shim has nothing after '--' to run")
    tokens = [str(entry.get("command", "")), *[str(a) for a in entry.get("args", [])]]
    script = next(t for t in tokens if t.endswith(SHIM_SUFFIX))
    for var in PLUGIN_ROOT_VARS:
        script = script.replace(var, str(root))
    path = Path(script)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        errors.append(f"  ✗ MCP server '{name}' shim script '{path}' not found")
    if not errors:
        errors.append(f"  ✓ MCP server '{name}' runs the lazy shim with '--name {name}'")
    return errors


def check_readme(root: Path, plugin_data: dict) -> list[str]:
    """README.md must link every shipped server (`servers/<key>`) and every skill (`skills/<dir>`)."""
    readme = root / "README.md"
    if not readme.is_file():
        return [f"  ✗ README.md not found at {readme}"]
    text = readme.read_text()
    errors = []
    keys = plugin_data.get("mcpServers", {})
    names = sorted({n.removesuffix(EXEC_SUFFIX) for n in keys})
    for name in names:
        if not re.search(rf"servers/{re.escape(name)}(?![\w-])", text):
            errors.append(f"  ✗ README.md does not link 'servers/{name}'")
    skills = sorted(p.name for p in (root / "skills").iterdir() if p.is_dir()) \
        if (root / "skills").is_dir() else []
    for name in skills:
        if not re.search(rf"skills/{re.escape(name)}(?![\w-])", text):
            errors.append(f"  ✗ README.md does not link 'skills/{name}'")
    if not errors:
        errors.append(f"  ✓ README.md lists all {len(names)} servers and {len(skills)} skills")
    return errors


def _has_arg(tokens: list[str], arg: tuple[str, ...]) -> bool:
    """True if `arg` is in `tokens`, as tokens or as its joined `-e=X` form."""
    return _strip_arg(tokens, arg) is not None


def _strip_arg(tokens: list[str], arg: tuple[str, ...]) -> list[str] | None:
    """Drop one occurrence of `arg` from `tokens`; None if absent."""
    n = len(arg)
    for i in range(len(tokens) - n + 1):
        if tuple(tokens[i:i + n]) == arg:
            return tokens[:i] + tokens[i + n:]
    joined = "=".join(arg)
    if joined in tokens:
        i = tokens.index(joined)
        return tokens[:i] + tokens[i + 1:]
    return None


def _check_exec_twin(name: str, base_name: str, base_declared: bool,
                     exec_args: list[str], base_args: list[str]) -> list[str]:
    """Check the invariant: same image, STORYBOARD_ALLOW_EXEC=1 and --network none."""
    errors = []
    if not base_declared:
        errors.append(f"  ✗ MCP server '{name}' has no base entry '{base_name}'")
    if not _has_arg(exec_args, EXEC_FLAG):
        errors.append(f"  ✗ MCP server '{name}' missing '-e STORYBOARD_ALLOW_EXEC=1'")
    if not _has_arg(exec_args, EXEC_NETWORK):
        errors.append(f"  ✗ MCP server '{name}' missing '--network none'")

    exec_image = exec_args[-1] if exec_args else None
    base_image = base_args[-1] if base_args else None
    if exec_image != base_image:
        errors.append(f"  ✗ MCP server '{name}' image '{exec_image}' != "
                      f"'{base_name}' image '{base_image}'")

    exec_rest, base_rest = list(exec_args), list(base_args)
    for arg in EXEC_ONLY_ARGS:
        stripped = _strip_arg(exec_rest, arg)
        if stripped is not None:
            exec_rest = stripped
    for arg in BASE_ONLY_ARGS:
        stripped = _strip_arg(base_rest, arg)
        if stripped is not None:
            base_rest = stripped
    extra = [a for a in exec_rest if a not in base_rest]
    missing = [a for a in base_rest if a not in exec_rest]
    if extra or missing:
        errors.append(f"  ✗ MCP server '{name}' args drift from '{base_name}': "
                      f"extra={extra} missing={missing}")

    if not errors:
        errors.append(f"  ✓ MCP server '{name}' is '{base_name}' + STORYBOARD_ALLOW_EXEC=1, no network")
    return errors


def check_yaml_frontmatter(md_path: Path, expected_name: str) -> list[str]:
    """Validate YAML frontmatter: exists, has required keys, name matches dir."""
    errors = []
    try:
        content = md_path.read_text()
    except Exception as e:
        return [f"  ✗ Cannot read: {e}"]

    # Extract frontmatter (simple parser, no external deps)
    lines = content.split('\n')
    if not lines[0].startswith('---'):
        errors.append("  ✗ No frontmatter (missing opening ---)")
        return errors

    fm_end = None
    for i, line in enumerate(lines[1:], 1):
        if line.startswith('---'):
            fm_end = i
            break

    if fm_end is None:
        errors.append("  ✗ Frontmatter not closed (missing closing ---)")
        return errors

    # Parse frontmatter for name and description
    fm_lines = lines[1:fm_end]
    found_name = None
    found_desc = False

    for line in fm_lines:
        if line.startswith('name:'):
            found_name = line.split('name:', 1)[1].strip()
        elif line.startswith('description:'):
            found_desc = True

    if found_name is None:
        errors.append("  ✗ Missing 'name:' in frontmatter")
    elif found_name != expected_name:
        errors.append(f"  ✗ name '{found_name}' doesn't match dir '{expected_name}'")

    if not found_desc:
        errors.append("  ✗ Missing 'description:' in frontmatter")

    if not errors:
        errors.append("  ✓ Valid frontmatter")

    return errors


def check_json_file(json_path: Path) -> list[str]:
    """Validate JSON syntax."""
    errors = []
    try:
        json.loads(json_path.read_text())
        errors.append("  ✓ Valid JSON")
    except json.JSONDecodeError as e:
        errors.append(f"  ✗ Invalid JSON: {e}")
    except Exception as e:
        errors.append(f"  ✗ Cannot read: {e}")
    return errors


def check_mcp_versions(root: Path, plugin_data: dict) -> list[str]:
    """A skill's `metadata.requires-mcp: "<server> <major.minor>"` must match the server's
    pyproject version, and every plugin.json entry for that image must pin exactly that version."""
    errors = []
    for md in sorted((root / "skills").glob("*/SKILL.md")):
        m = re.search(r'^\s+requires-mcp:\s*"?([\w-]+) (\d+\.\d+)"?\s*$', md.read_text(), re.M)
        if not m:
            continue
        name, prefix = m.groups()
        version = None
        for pyproject in (root / "servers").glob("*/pyproject.toml"):
            text = pyproject.read_text()
            if re.search(rf'^name = "{re.escape(name)}"', text, re.M):
                version = (re.search(r'^version = "([^"]+)"', text, re.M) or [None, None])[1]
        label = f"Skill '{md.parent.name}' requires {name} {prefix}"
        if version is None:
            errors.append(f"  ✗ {label}: no server with that name/version in servers/*/pyproject.toml")
            continue
        if not version.startswith(prefix + "."):
            errors.append(f"  ✗ {label}, but the server is {version}")
        # the image is the last element of the real command, shim wrapper or not
        pins = [real_argv(e)[-1] for e in plugin_data.get("mcpServers", {}).values() if real_argv(e)]
        pins = [p for p in pins if f"/{name}:" in p]
        bad = [p for p in pins if p.rsplit(":", 1)[1] != version]
        if not pins or bad:
            errors.append(f"  ✗ plugin.json must pin {name}:{version} in every entry (found {pins or 'none'})")
        elif version.startswith(prefix + "."):
            errors.append(f"  ✓ {label} = {version}, pinned in plugin.json")
    return errors


def check_references(plugin_json: Path, marketplace_json: Path) -> list[str]:
    """Verify skills, servers, commands referenced in JSONs exist on disk."""
    errors = []
    root = plugin_json.parent.parent
    skills_dir = root / "skills"
    servers_dir = root / "servers"
    commands_dir = root / "commands"

    try:
        plugin_data = json.loads(plugin_json.read_text())
    except Exception as e:
        return [f"  ✗ Cannot parse plugin.json: {e}"]

    # Check MCP servers
    mcp_servers = plugin_data.get("mcpServers", {})
    for server_name, entry in mcp_servers.items():
        # the `-exec` entry runs the same image with STORYBOARD_ALLOW_EXEC=1: one directory, two entries
        is_exec = server_name.endswith(EXEC_SUFFIX)
        dir_name = server_name[:-len(EXEC_SUFFIX)] if is_exec else server_name
        server_path = servers_dir / dir_name
        if not server_path.is_dir():
            errors.append(f"  ✗ MCP server '{server_name}' not found in servers/")
        else:
            errors.append(f"  ✓ MCP server '{server_name}' exists")
        argv = real_argv(entry)  # the shim keeps the docker argv after `--`
        errors.extend(check_shim_entry(server_name, entry, root))
        if is_exec:
            errors.extend(_check_exec_twin(
                server_name, dir_name, dir_name in mcp_servers,
                argv, real_argv(mcp_servers.get(dir_name, {})),
            ))
        elif any("STORYBOARD_ALLOW_EXEC" in a for a in argv):
            errors.append(f"  ✗ MCP server '{server_name}' must not set STORYBOARD_ALLOW_EXEC")

    errors.extend(check_mcp_versions(root, plugin_data))

    # Check referenced skills (from description parsing). Whole names only: 'security-review'
    # must not be credited by the 'security-review-web-api' entry of the same description.
    desc = plugin_data.get("description", "")
    for skill_name in ["deep-clean", "doc-audit", "guided-build", "icon-search", "image",
                       "music-search", "pr-opener", "refactor", "screencapture",
                       "security-review", "security-review-binary-c", "security-review-web-api",
                       "tech-blog-post"]:
        if re.search(rf"(?<![\w-]){re.escape(skill_name)}(?![\w-])", desc):
            skill_path = skills_dir / skill_name
            if not skill_path.is_dir():
                errors.append(f"  ✗ Skill '{skill_name}' referenced but not found")
            elif not (skill_path / "SKILL.md").exists():
                errors.append(f"  ✗ Skill '{skill_name}' dir exists but no SKILL.md")
            else:
                errors.append(f"  ✓ Skill '{skill_name}' exists with SKILL.md")

    # Check all skills have SKILL.md
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    errors.append(f"  ✗ Skill '{skill_dir.name}' missing SKILL.md")

    # README documents everything this plugin ships (servers minus `-exec`, and every skill)
    errors.extend(check_readme(root, plugin_data))

    return errors


def main():
    """Run all validation checks."""
    root = Path(__file__).parent.parent
    skills_dir = root / "skills"
    plugin_json = root / ".claude-plugin" / "plugin.json"
    marketplace_json = root / ".claude-plugin" / "marketplace.json"

    print("=" * 60)
    print("PLUGIN VALIDATION")
    print("=" * 60)

    all_errors = []
    has_failures = False

    # 1. Validate SKILL.md files
    print("\n[SKILLS] Checking SKILL.md files...")
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                print(f"\n  {skill_dir.name}/SKILL.md:")
                if not skill_md.exists():
                    print(f"    ✗ File not found")
                    has_failures = True
                else:
                    errors = check_yaml_frontmatter(skill_md, skill_dir.name)
                    for err in errors:
                        print(err)
                        if "✗" in err:
                            has_failures = True
                    all_errors.extend(errors)

    # 2. Validate JSON files
    print("\n[JSON] Checking plugin configuration...")
    print(f"\n  plugin.json:")
    plugin_errors = check_json_file(plugin_json)
    for err in plugin_errors:
        print(err)
        if "✗" in err:
            has_failures = True

    print(f"\n  marketplace.json:")
    marketplace_errors = check_json_file(marketplace_json)
    for err in marketplace_errors:
        print(err)
        if "✗" in err:
            has_failures = True

    # 3. Check references (servers, skills, README)
    print("\n[REFERENCES] Checking disk and README references...")
    ref_errors = check_references(plugin_json, marketplace_json)
    for err in ref_errors:
        print(err)
        if "✗" in err:
            has_failures = True

    # Summary
    print("\n" + "=" * 60)
    if has_failures:
        print("RESULT: ✗ FAILURES FOUND")
        sys.exit(1)
    else:
        print("RESULT: ✓ ALL CHECKS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
