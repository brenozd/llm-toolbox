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
mkdir -p "$config_dir"
scaffolded=""
blocked=""
for name in actual-budget woodpecker; do
  target="$config_dir/$name.json"
  if [ -d "$target" ]; then
    # docker creates a dir here if it ran before the file existed; can't fix without sudo
    blocked+="$name "
  elif [ ! -f "$target" ]; then
    example="${CLAUDE_PLUGIN_ROOT}/servers/$name/config.example.json"
    if [ -f "$example" ]; then
      cp "$example" "$target"
      scaffolded+="$name "
    fi
  fi
done

if [ -n "$scaffolded" ]; then
  context+=$'\n\n'"Scaffolded llm-toolbox MCP config(s) from config.example.json: $scaffolded"'(placeholder values at ~/.config/llm-toolbox/<name>.json). At a natural point this session, mention it once and offer to fill in the real values (ask the user, don'"'"'t guess secrets) — do not block on it or repeat the offer.'
fi

if [ -n "$blocked" ]; then
  cmd=""
  for name in $blocked; do
    cmd+="$config_dir/$name.json "
  done
  context+=$'\n\n'"llm-toolbox MCP config path(s) are root-owned empty directories instead of files, so they can't be auto-fixed: $blocked"'. Tell the user once to run: sudo rmdir '"$cmd"
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
