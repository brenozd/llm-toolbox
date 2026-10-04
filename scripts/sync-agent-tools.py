#!/usr/bin/env python3
"""Keep agents/*.md `tools:` valid in both Pi and Claude Code.

Write the Pi (lowercase) names in `tools:`; this script rewrites it to
"<Claude names>, <Pi names>" and adds `excludeTools: <Claude names>`.
  - Claude Code: names are case-sensitive; unknown entries and the unknown
    `excludeTools` field are ignored.
  - Pi: an unknown name in `tools` fails the launch, but `excludeTools` is
    stripped from the allowlist first.
Verified 2026-10-04 (Claude Code 2.1.289, pi-subagents). Re-verify on major
upgrades: if Claude Code ever adds `excludeTools` semantics, this breaks.
Exits 1 when it changed a file (pre-commit idiom) or finds an unknown name.
"""
import re
import sys
from pathlib import Path

# Pi name -> Claude Code name (None: no Claude equivalent, Bash covers it)
PI_TO_CLAUDE = {
    "read": "Read", "grep": "Grep", "find": "Glob", "ls": None, "bash": "Bash",
    "edit": "Edit", "write": "Write", "web_search": "WebSearch",
    "fetch_content": "WebFetch", "subagent": "Agent",
}
FM = re.compile(r"\A---\n(.*?\n)---\n", re.S)


def main() -> int:
    bad = False
    for path in sorted(Path(__file__).parent.parent.glob("agents/*.md")):
        text = path.read_text()
        m = FM.match(text)
        if not m or not re.search(r"^tools:", m[1], re.M):
            continue
        fm = re.sub(r"^excludeTools:.*\n", "", m[1], flags=re.M)
        raw = re.search(r"^tools:(.*)$", fm, re.M)[1].split(",")
        pi = list(dict.fromkeys(t.strip() for t in raw if t.strip() and t.strip().islower()))
        unknown = [t for t in pi if t not in PI_TO_CLAUDE]
        if unknown:
            print(f"{path}: unknown tool(s) {unknown}; add to PI_TO_CLAUDE")
            bad = True
            continue
        claude = [PI_TO_CLAUDE[t] for t in pi if PI_TO_CLAUDE[t]]
        both = ", ".join(claude + pi)
        new = re.sub(r"^tools:.*$", f"tools: {both}", fm, flags=re.M)
        if claude:
            new = re.sub(r"^(tools:.*\n)", rf"\1excludeTools: {', '.join(claude)}\n", new, flags=re.M)
        if new != m[1]:
            path.write_text(f"---\n{new}---\n{text[m.end():]}")
            print(f"updated {path}")
            bad = True
    return int(bad)


if __name__ == "__main__":
    sys.exit(main())
