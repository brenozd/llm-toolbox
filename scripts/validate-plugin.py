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
        pins = [str(e.get("args", [""])[-1]) for e in plugin_data.get("mcpServers", {}).values()]
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
        if is_exec:
            errors.extend(_check_exec_twin(
                server_name, dir_name, dir_name in mcp_servers,
                [str(a) for a in entry.get("args", [])],
                [str(a) for a in mcp_servers.get(dir_name, {}).get("args", [])],
            ))
        elif any("STORYBOARD_ALLOW_EXEC" in str(a) for a in entry.get("args", [])):
            errors.append(f"  ✗ MCP server '{server_name}' must not set STORYBOARD_ALLOW_EXEC")

    errors.extend(check_mcp_versions(root, plugin_data))

    # Check referenced skills (from description parsing)
    desc = plugin_data.get("description", "")
    for skill_name in ["deep-clean", "doc-audit", "guided-build", "image", "screencapture", "tech-blog-post", "refactor", "icon-search", "music-search", "pr-opener"]:
        if skill_name in desc:
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

    # 3. Check references
    print("\n[REFERENCES] Checking disk references...")
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
