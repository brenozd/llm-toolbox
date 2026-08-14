#!/usr/bin/env bash
# Injects terse/caveman-style response instructions as SessionStart additionalContext,
# but only when the user has toggled it on via /terse-mode. Also flags any
# llm-toolbox MCP server missing its config.json, so Claude can offer setup.
set -euo pipefail

state_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/llm-toolbox"
marker="$state_dir/terse-mode"

context=""

if [ -f "$marker" ]; then
  context+="$(cat "${CLAUDE_PLUGIN_ROOT}/hooks/terse-style.txt")"
fi

config_dir="$HOME/.config/llm-toolbox"
missing=""
for name in actual-budget woodpecker; do
  if [ ! -f "$config_dir/$name.json" ]; then
    missing+="$name "
  fi
done

if [ -n "$missing" ]; then
  context+=$'\n\n'"llm-toolbox MCP server(s) missing config, so they will fail to connect: $missing"'(no config.json at ~/.config/llm-toolbox/<name>.json). At a natural point this session, mention it once and offer to scaffold the file from servers/<name>/config.example.json in the llm-toolbox repo — do not block on it or repeat the offer.'
fi

if [ -z "$context" ]; then
  exit 0
fi

python3 -c '
import json, sys
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": sys.argv[1],
    }
}))
' "$context"
