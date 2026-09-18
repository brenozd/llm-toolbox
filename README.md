# llm-toolbox

[![status-badge](https://woodpecker.bzd.gg/api/badges/6/status.svg)](https://woodpecker.bzd.gg/repos/6)

MCP servers packaged as OCI containers, in Python, plus reusable Claude Code skills.

## Install

```
/plugin marketplace add https://git.bzd.gg/bzd/llm-toolbox.git
/plugin install llm-toolbox@llm-toolbox
```

`owner/repo` shorthand only works for github.com — this repo is self-hosted
Forgejo, so use the full clone URL above. See [INSTALL.md](INSTALL.md) for
local-checkout, manual-symlink, Gemini CLI, and MCP server setups.

## Servers

- [`servers/actual-budget`](servers/actual-budget/) — integrates with [Actual Budget](https://actualbudget.org).
- [`servers/woodpecker`](servers/woodpecker/) — integrates with [Woodpecker CI/CD](https://woodpecker-ci.org).
- [`servers/faster-whisper`](servers/faster-whisper/) — speech-to-text transcription via faster-whisper.

## Skills

- [`skills/deep-clean`](skills/deep-clean/) — iterative find-and-fix sweep: scan, triage, fix, rescan until clean.
- [`skills/distrobox`](skills/distrobox/) — persistent per-project distrobox container to build/test in isolation from the host.
- [`skills/doc-audit`](skills/doc-audit/) — syncs documentation with current code implementation.
- [`skills/guided-build`](skills/guided-build/) — goal-first, checkpoint-driven build process.
- [`skills/icon-search`](skills/icon-search/) — searches SVG icons (Iconify, OpenIconLibrary, Flaticon) with license info.
- [`skills/image`](skills/image/) — crop/rotate/resize/blur/watermark and other light edits with Python + Pillow.
- [`skills/pr-opener`](skills/pr-opener/) — opens a PR: verifies work, drafts title/body from the diff vs base, pushes, creates draft PR (forge-agnostic).
- [`skills/refactor`](skills/refactor/) — plans then executes a multi-file refactor phase by phase, with verification and rollback.
- [`skills/screenshot`](skills/screenshot/) — captures desktop/web screenshots with Python + Pillow (Linux/macOS/Windows).
- [`skills/tech-blog-post`](skills/tech-blog-post/) — writes a technical blog post in a senior-engineer voice.
- [`skills/ui-review`](skills/ui-review/) — audits a web UI for usability, accessibility, performance, and visual consistency.

These skills are written for and depend on the following plugin (install it separately):

- [ponytail](https://github.com/DietrichGebert/ponytail) — lazy/minimal-solution enforcement mode.

## Commands

- `/terse-mode on|off|status` — toggles a terse, filler-free response style. State lives in
  `${CLAUDE_CONFIG_DIR:-~/.claude}/llm-toolbox/terse-mode`; a `SessionStart` hook injects the
  style as additional context on the next session when on. Off by default.
- `/shadow-agents on|off|status` — toggles llm-toolbox's cheaper `explore`/`plan`/`general-purpose`
  agent overrides (haiku model, restricted tools, tighter scope — see [`agents/`](agents/)).
  Off by default; a `SessionStart` hook symlinks them into `${CLAUDE_CONFIG_DIR:-~/.claude}/agents/`
  once toggled on, and injects a reminder — in every project, not just this repo — to skip
  delegating to a subagent for tasks a direct answer already covers.

## Agents

- [`agents/`](agents/) — cheaper drop-in overrides for the built-in `explore`, `plan`, and
  `general-purpose` subagents (haiku, restricted tool lists, tighter scope rules). Not applied
  automatically on install — opt in with `/shadow-agents on`.
