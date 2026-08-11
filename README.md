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

## Skills

- [`skills/caveman-sweep`](skills/caveman-sweep/) — iterative find-and-fix sweep: scan, triage, fix, rescan until clean.
- [`skills/doc-audit`](skills/doc-audit/) — syncs documentation with current code implementation.
- [`skills/guided-build`](skills/guided-build/) — goal-first, checkpoint-driven build process.
- [`skills/icon-search`](skills/icon-search/) — searches SVG icons (Iconify, OpenIconLibrary, Flaticon) with license info.
- [`skills/image`](skills/image/) — crop/rotate/resize/blur/watermark and other light edits with Python + Pillow.
- [`skills/screenshot`](skills/screenshot/) — captures desktop/web screenshots with Python + Pillow (Linux/macOS/Windows).
- [`skills/tech-blog-post`](skills/tech-blog-post/) — writes a technical blog post in a senior-engineer voice.

These skills are written for and depend on the following plugins (install them separately):

- [caveman](https://github.com/JuliusBrussee/caveman) — ultra-compressed communication mode.
- [ponytail](https://github.com/DietrichGebert/ponytail) — lazy/minimal-solution enforcement mode.
