---
description: "Toggle shadowing of built-in explore/plan/general-purpose agents with llm-toolbox's cheaper haiku-backed versions"
argument-hint: "[on|off|status]"
allowed-tools: ["Bash(mkdir -p*)", "Bash(touch*)", "Bash(rm -f*)", "Bash(test -f*)", "Bash(ln -sf*)", "Bash(rm -f*)"]
---

# Shadow agents

Argument: `$ARGUMENTS` (expect `on`, `off`, or `status` — default to `status` if empty).

llm-toolbox ships lighter replacements for the built-in `explore`, `plan`,
and `general-purpose` subagents in `${CLAUDE_PLUGIN_ROOT}/agents/` (haiku
model, restricted tools, tighter scope). They're opt-in: shadowing only
takes effect once toggled on, so installing the plugin alone doesn't change
subagent behavior. When on, the `SessionStart` hook also injects a
reminder — in every project, not just where this file lives — not to
delegate to a subagent for anything a direct answer already covers
(`hooks/no-unnecessary-delegation.txt`).

State dir: `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/llm-toolbox`
Marker file: `<state dir>/shadow-agents`
Agents dir: `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agents`

1. **on**: `mkdir -p "<state dir>"` then `touch "<state dir>/shadow-agents"`.
   Then symlink each file in `${CLAUDE_PLUGIN_ROOT}/agents/` into `<agents dir>`
   (`mkdir -p "<agents dir>"`, `ln -sf "${CLAUDE_PLUGIN_ROOT}/agents/<name>.md" "<agents dir>/<name>.md"`
   for `explore`, `plan`, `general-purpose`). Report: shadow agents on.
2. **off**: `rm -f "<state dir>/shadow-agents"`, then remove the three symlinks
   from `<agents dir>` (only if they point into `${CLAUDE_PLUGIN_ROOT}/agents/` —
   don't touch a file the user created themselves with the same name). Report: shadow agents off, built-ins restored.
3. **status**: `test -f "<state dir>/shadow-agents"` and report on/off accordingly.

Keep the report to one line.
