#!/usr/bin/env bash
# Injects terse/caveman-style response instructions as SessionStart additionalContext,
# but only when the user has toggled it on via /terse-mode.
set -euo pipefail

state_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/llm-toolbox"
marker="$state_dir/terse-mode"

if [ ! -f "$marker" ]; then
  exit 0
fi

style_file="${CLAUDE_PLUGIN_ROOT}/hooks/terse-style.txt"

python3 -c '
import json, sys
with open(sys.argv[1]) as f:
    style = f.read()
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": style,
    }
}))
' "$style_file"
