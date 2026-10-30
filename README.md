# llm-toolbox

<img src="icon.svg" width="64" height="64" alt="llm-toolbox icon">

[![status-badge](https://woodpecker.bzd.gg/api/badges/6/status.svg)](https://woodpecker.bzd.gg/repos/6)

MCP servers packaged as OCI containers, in Python, plus reusable Claude Code skills.

## Install

```
/plugin marketplace add https://git.bzd.gg/bzd/llm-toolbox.git
/plugin install llm-toolbox@llm-toolbox
```

`owner/repo` shorthand only works for github.com — this repo is self-hosted
Forgejo, so use the full clone URL above. See [INSTALL.md](INSTALL.md) for
local-checkout, manual-symlink, Gemini CLI, Pi, and MCP server setups.

For [Pi](https://pi.dev):

```
pi install git:git.bzd.gg/bzd/llm-toolbox
```

## Servers

- [`servers/actual-budget`](servers/actual-budget/) — integrates with [Actual Budget](https://actualbudget.org).
- [`servers/woodpecker`](servers/woodpecker/) — integrates with [Woodpecker CI/CD](https://woodpecker-ci.org).
- [`servers/vikunja`](servers/vikunja/) — projects, tasks, comments and labels of a [Vikunja](https://vikunja.io) instance.
- [`servers/faster-whisper`](servers/faster-whisper/) — speech-to-text transcription via faster-whisper.
- [`servers/promo-video`](servers/promo-video/) — turns a repo (web, CLI or GUI) into an evidence-checked promo video: scan, capture, validate spec, render MP4, verify.
- [`servers/whatsapp`](servers/whatsapp/) — read WhatsApp chats and (opt-in) send messages, through an in-process whatsmeow client (neonize).

## Skills

- [`skills/code-tutor`](skills/code-tutor/) — programming tutor: profiles the project's domain, reviews your diff with linters/compilers, hints instead of fixes. Pi extension (`/tutor`) adds toggle, edit/write block and an auto-review watcher.
- [`skills/distrobox`](skills/distrobox/) — persistent per-project distrobox container to build/test in isolation from the host.
- [`skills/guided-build`](skills/guided-build/) — goal-first, checkpoint-driven build process.
- [`skills/icon-search`](skills/icon-search/) — searches SVG icons (Iconify, OpenIconLibrary, Flaticon) with license info.
- [`skills/image`](skills/image/) — crop/rotate/resize/blur/watermark and other light edits with Python + Pillow.
- [`skills/music-search`](skills/music-search/) — finds a licence-cleared music bed (Openverse, Internet Archive, ccMixter, Commons), verifies the licence at the origin and stages it for promo-video.
- [`skills/promo-video`](skills/promo-video/) — workflow for the promo-video MCP: honest storyboard from the code, review stills, render, verify.
- [`skills/pr-opener`](skills/pr-opener/) — opens a PR: verifies work, drafts title/body from the diff vs base, pushes, creates draft PR (forge-agnostic).
- [`skills/screenshot`](skills/screenshot/) — captures desktop/web screenshots with Python + Pillow (Linux/macOS/Windows).
- [`skills/svg-generator`](skills/svg-generator/) — hand-writes SVG markup via a write/render/self-evaluate/revise loop.
- [`skills/tech-blog-post`](skills/tech-blog-post/) — writes a technical blog post in a senior-engineer voice.
- [`skills/ui-review`](skills/ui-review/) — full multi-agent web UI review (UX, visual, a11y, responsiveness), consolidated into one prioritized report.
- [`skills/wiki-writing`](skills/wiki-writing/) — writes/audits dense, verified technical wiki pages (reference, explanation, runbook, ADR, postmortem) with a numbers-consistency check and independent review.

## Icon

- [`icon.svg`](icon.svg) — light background.
- [`icon-dark.svg`](icon-dark.svg) — dark background.
- [`icon-mono.svg`](icon-mono.svg) — single color, uses `currentColor` (set `color` on a parent).

These skills are written for and depend on the following plugin (install it separately):

- [ponytail](https://github.com/DietrichGebert/ponytail) — lazy/minimal-solution enforcement mode.

## Agents

- [`agents/`](agents/) — standalone subagents for isolated-context/async work: `deep-clean`
  (find-and-fix sweep), `doc-audit` (sync docs with code), `refactor` (phased multi-file
  refactor), `ui-review` (web UI audit), `debug` (reproduce/root-cause/fix/verify),
  `devils-advocate` (stress-test an idea), `pr-review` (evidence-first PR review, read-only until approved; delegates finding checks to `pr-review-verifier`), `expert-embedded-c-engineer` (MISRA/CERT C,
  standard-aware), `expert-cpp-software-engineer` (modern C++, standard-aware),
  `se-ux-ui-designer` (JTBD analysis and journey mapping). Self-contained, no skill dependency. Under Claude Code
  they load from `agents/` automatically as plugin subagents. Under [Pi](https://pi.dev), they
  require the [pi-subagents](https://github.com/nicobailon/pi-subagents) extension installed
  separately; this package declares them via `pi.subagents.agents` in `package.json`, so once
  pi-subagents is installed, `pi install git:git.bzd.gg/bzd/llm-toolbox` picks them up.

Agent `tools:` lines list both Claude Code and Pi names. Edit only the lowercase
(Pi) names, then run `scripts/sync-agent-tools.py` (also a pre-commit hook) to
regenerate `tools:` and `excludeTools:` — see the script header for why.
