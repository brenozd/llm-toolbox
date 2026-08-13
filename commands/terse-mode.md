---
description: "Toggle terse/caveman-style response mode on or off"
argument-hint: "[on|off|status]"
allowed-tools: ["Bash(mkdir -p*)", "Bash(touch*)", "Bash(rm -f*)", "Bash(test -f*)"]
---

# Terse mode

Argument: `$ARGUMENTS` (expect `on`, `off`, or `status` — default to `status` if empty).

State dir: `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/llm-toolbox`
Marker file: `<state dir>/terse-mode`

1. **on**: `mkdir -p "<state dir>"` then `touch "<state dir>/terse-mode"`. Report: terse mode on, takes effect next session (SessionStart hook).
2. **off**: `rm -f "<state dir>/terse-mode"`. Report: terse mode off, takes effect next session.
3. **status**: `test -f "<state dir>/terse-mode"` and report on/off accordingly.

Keep the report to one line.
