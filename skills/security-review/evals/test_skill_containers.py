"""Smoke test: every checker command documented by security-review-containers runs.

CI has no hadolint/trivy/docker daemon, so the executable part is the offline checker the
skill cites (`evals/fixtures/poc_field.py`): seeded artifact -> marker, fixed twin -> none.
The commands are parsed out of the markdown, so a doc that drifts from the fixture fails.
"""

import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "security-review-containers"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CHECKER = FIXTURES / "poc_field.py"
CONTAINERS = FIXTURES / "containers"
DOCS = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]

# `--kind dockerfile --field root-user --file $F/Dockerfile` as written in SKILL.md
COMMAND = re.compile(r"--kind\s+(\w+)\s+--field\s+([\w-]+)\s+--file\s+(\S+)")


def _frontmatter(path):
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path} has no YAML frontmatter"
    return dict(
        (k.strip(), v.strip().strip('"'))
        for k, _, v in (line.partition(":") for line in match.group(1).splitlines()
                        if ":" in line)
        if k.strip() in ("name", "description", "version")
    )


def test_frontmatter_matches_the_sibling_contract():
    meta = _frontmatter(SKILL / "SKILL.md")
    assert meta["name"] == SKILL.name
    assert re.fullmatch(r"\d+\.\d+\.\d+", meta["version"])
    assert "Use for:" in meta["description"]
    assert f"/{SKILL.name}" in meta["description"]


def test_references_linked_from_skill_exist():
    text = (SKILL / "SKILL.md").read_text()
    linked = set(re.findall(r"`(references/[\w-]+\.md)`", text))
    assert linked, "SKILL.md links no reference files"
    for rel in linked:
        assert (SKILL / rel).is_file(), f"SKILL.md links missing {rel}"


def test_documented_checker_commands_confirm_the_seed_and_spare_the_control():
    import pytest

    pytest.importorskip("yaml", reason="compose checks need PyYAML")
    commands = {
        (kind, field, path.replace("$F/", "").replace("$F", ""))
        for doc in DOCS
        for kind, field, path in COMMAND.findall(doc.read_text())
    }
    assert len(commands) >= 6, f"SKILL.md should document 4 seeds + 2 controls, got {commands}"
    for kind, field, name in sorted(commands):
        artifact = CONTAINERS / name
        assert artifact.is_file(), f"documented artifact {name} does not exist"
        run = subprocess.run(
            [sys.executable, str(CHECKER), "--kind", kind, "--field", field,
             "--file", str(artifact)],
            capture_output=True, text=True, timeout=60,
        )
        assert run.returncode == 0, f"{name}: {run.stderr}"
        if ".fixed" in name:
            assert run.stdout == "", f"control {name} still printed {run.stdout!r}"
        else:
            assert re.fullmatch(r"[A-Z_]+_CONFIRMED\n", run.stdout), \
                f"{name} did not confirm {kind}/{field}: {run.stdout!r}"
