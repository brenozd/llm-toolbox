#!/usr/bin/env bash
# Bumps patch version in .claude-plugin/{plugin,marketplace}.json whenever
# staged changes touch skills/ or servers/, so the marketplace picks up an update.
set -euo pipefail

changed=$(git diff --cached --name-only --diff-filter=ACMR)

grep -qE '^(skills|servers)/' <<<"$changed" || exit 0

for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json; do
  ver=$(jq -r .version "$f")
  IFS=. read -r major minor patch <<<"$ver"
  new="$major.$minor.$((patch + 1))"
  jq --arg v "$new" '.version = $v' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  git add "$f"
done
