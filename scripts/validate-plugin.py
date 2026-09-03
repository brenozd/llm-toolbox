#!/usr/bin/env python3
"""Validate plugin structure: SKILL.md frontmatter, JSON config, and disk references."""

import json
import sys
from pathlib import Path


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
    for server_name in mcp_servers.keys():
        server_path = servers_dir / server_name
        if not server_path.is_dir():
            errors.append(f"  ✗ MCP server '{server_name}' not found in servers/")
        else:
            errors.append(f"  ✓ MCP server '{server_name}' exists")

    # Check referenced skills (from description parsing)
    desc = plugin_data.get("description", "")
    for skill_name in ["deep-clean", "doc-audit", "guided-build", "image", "screenshot", "tech-blog-post", "refactor", "icon-search", "pr-opener"]:
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
