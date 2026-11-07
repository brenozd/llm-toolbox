# llm-toolbox

MCP servers packaged as OCI containers (Python), plus reusable agent skills, subagents and Pi extensions.

> This repository is a public mirror. The origin is self-hosted: CI runs on a
> self-hosted Woodpecker instance and the OCI images are published to
> `harbor.bzd.gg`.

<img src="icon.svg" width="64" height="64" alt="llm-toolbox icon">

## Overview

- **MCP servers** — one container image per integration, published to `harbor.bzd.gg`. The plugin runs each of them through `scripts/lazy-mcp.py`, a stdlib-only shim that answers the MCP handshake from a cache and starts the container only when a tool is actually called (see [Resource usage](#resource-usage-and-lazy-loading)).
- **Skills** — `SKILL.md` workflows shared by Claude Code, Pi, Gemini CLI and other `SKILL.md`-compatible agents.
- **Agents** — standalone subagents for isolated-context or async work.
- **Extensions** — Pi extensions (`extensions/tutor`, `extensions/safe-bash`) shipped with the package.

Everything here is deliberately small: each server is a single-purpose Python MCP server, each skill is a set of instructions, and no server runs longer than it is being used — with one deliberate exception, `whatsapp`, which is never idle-stopped (its pairing session degrades on restart, so it runs with `LAZY_MCP_IDLE_SECONDS=0`; see [Resource usage](#resource-usage-and-lazy-loading)).

### Agents

[`agents/`](agents/) holds self-contained subagents, with no skill dependency: `deep-clean` (find-and-fix sweep), `doc-audit` (sync docs with code), `refactor` (phased multi-file refactor), `ui-review` (web UI audit), `debug` (reproduce/root-cause/fix/verify), `devils-advocate` (stress-test an idea), `pr-review` (evidence-first PR review, read-only until approved; delegates finding checks to `pr-review-verifier`), `expert-embedded-c-engineer` (MISRA/CERT C, standard-aware), `expert-cpp-software-engineer` (modern C++, standard-aware), `se-ux-ui-designer` (JTBD analysis and journey mapping).

Under Claude Code they load from `agents/` automatically as plugin subagents. Under [Pi](https://pi.dev) they require the [pi-subagents](https://github.com/nicobailon/pi-subagents) extension installed separately; this package declares them via `pi.subagents.agents` in `package.json`, so once pi-subagents is installed, `pi install git:github.com/brenozd/llm-toolbox` picks them up.

Agent `tools:` lines list both Claude Code and Pi names. Edit only the lowercase (Pi) names, then run `scripts/sync-agent-tools.py` (also a pre-commit hook) to regenerate `tools:` and `excludeTools:` — see the script header for why.

### Icon

- [`icon.svg`](icon.svg) — light background.
- [`icon-dark.svg`](icon-dark.svg) — dark background.
- [`icon-mono.svg`](icon-mono.svg) — single color, uses `currentColor` (set `color` on a parent).

## Quick start

Claude Code:

```
/plugin marketplace add https://github.com/brenozd/llm-toolbox.git
/plugin install llm-toolbox@llm-toolbox
```

[Pi](https://pi.dev):

```
pi install git:github.com/brenozd/llm-toolbox
```

Local checkouts, manual skill symlinks, Gemini CLI, Cursor, Codex CLI, and the JSON for non-plugin MCP clients are in [INSTALL.md](INSTALL.md).

## Servers

| Server | What it does | Image | Version | Network | Mounts |
| --- | --- | --- | --- | --- | --- |
| [`servers/actual-budget`](servers/actual-budget/) | Accounts, transactions, categories and budgets of an [Actual Budget](https://actualbudget.org) instance | [`harbor.bzd.gg/bzd/actual-budget-mcp`](https://harbor.bzd.gg/harbor/projects/bzd/repositories/actual-budget-mcp) | `0.6.0` | bridge | `~/.config/llm-toolbox/actual-budget.json` read-only; volume `actual-budget-data` |
| [`servers/woodpecker`](servers/woodpecker/) | Orgs, repos, pipelines, secrets and registries of a [Woodpecker CI/CD](https://woodpecker-ci.org) instance | [`harbor.bzd.gg/bzd/woodpecker-mcp`](https://harbor.bzd.gg/harbor/projects/bzd/repositories/woodpecker-mcp) | `0.1.0` | bridge | `~/.config/llm-toolbox/woodpecker.json` read-only |
| [`servers/vikunja`](servers/vikunja/) | Projects, tasks, comments and labels of a [Vikunja](https://vikunja.io) instance | [`harbor.bzd.gg/bzd/vikunja-mcp`](https://harbor.bzd.gg/harbor/projects/bzd/repositories/vikunja-mcp) | `0.1.0` | bridge | `~/.config/llm-toolbox/vikunja.json` read-only |
| [`servers/audio-transcribe`](servers/audio-transcribe/) | Speech-to-text transcription via Parakeet (transcribe-cpp) | [`harbor.bzd.gg/bzd/audio-transcribe-mcp`](https://harbor.bzd.gg/harbor/projects/bzd/repositories/audio-transcribe-mcp) | `0.3.0` | bridge | `$HOME` read-only; `~/.cache/huggingface` read-write for model weights |
| [`servers/document-ocr`](servers/document-ocr/) | Text from images and PDFs: embedded text layer first, Tesseract otherwise | [`harbor.bzd.gg/bzd/document-ocr-mcp`](https://harbor.bzd.gg/harbor/projects/bzd/repositories/document-ocr-mcp) | `0.1.0` | none | `~/.config/llm-toolbox/whatsapp-downloads` read-only (the whatsapp server's download root) |
| [`servers/whatsapp`](servers/whatsapp/) | Read WhatsApp chats and, opt-in, send messages through an in-process whatsmeow client (neonize) | [`harbor.bzd.gg/bzd/whatsapp-mcp`](https://harbor.bzd.gg/harbor/projects/bzd/repositories/whatsapp-mcp) | `0.2.0` | bridge | `~/.config/llm-toolbox/whatsapp.json` read-only; volume `whatsapp-data`; `whatsapp-media` read-only; `whatsapp-downloads` read-write |
| [`servers/storyboard-video`](servers/storyboard-video/) | Turns a repo (web, CLI or GUI) into an evidence-checked promo video: scan, capture, validate spec, render MP4, verify | [`harbor.bzd.gg/bzd/storyboard-video-mcp`](https://harbor.bzd.gg/harbor/projects/bzd/repositories/storyboard-video-mcp) | `0.2.0` | bridge (`host.docker.internal` mapped for web capture) | `${PWD}` read-only at `/repo`; volume `storyboard-video-work`; `~/.cache/storyboard-video/music` and `/sfx` read-only |

`storyboard-video-exec` is the same image as a second entry with `--network none` and `STORYBOARD_ALLOW_EXEC=1`: it runs the commands (CLI/GUI captures) that the base entry refuses. Versions are kept in sync with each `servers/*/pyproject.toml` by `scripts/release.py`, which also pins the image tags.

## Skills

| Skill | What it does |
| --- | --- |
| [`skills/code-tutor`](skills/code-tutor/) | Programming tutor that reviews your real code (git diff) on language, domain and project layers; gives the smallest useful hint and the why, never edits files. The Pi extension `/tutor` adds a toggle, an edit/write block and an auto-review watcher. |
| [`skills/distrobox`](skills/distrobox/) | Persistent per-project distrobox container (Ubuntu 24.04, systemd) to build and test code isolated from the host. |
| [`skills/grilling`](skills/grilling/) | Relentless decision-tree interview, one round of questions at a time, each with a recommended answer, to stress-test a plan; adapted from mattpocock/skills. |
| [`skills/guided-build`](skills/guided-build/) | Goal-first, checkpoint-driven build: interviews you for the real goal, researches the web, plans in buckets, stress-tests the plan with experts and an adversarial review, then verifies each bucket. |
| [`skills/icon-search`](skills/icon-search/) | Search SVG icons by keyword with licenses (Iconify, OpenIconLibrary, Flaticon). |
| [`skills/image`](skills/image/) | Light image editing with Python + Pillow: crop, rotate, resize, blur, grayscale, watermark, format conversion (PNG/JPEG/WebP). |
| [`skills/music-search`](skills/music-search/) | Finds a licence-cleared music bed (Openverse, Internet Archive; `--kind sfx` for CC0 sound effects), verifies the licence at the origin and stages it for storyboard-video. |
| [`skills/openscad-part`](skills/openscad-part/) | Models a 3D-printable (FDM) part in OpenSCAD: interview, spec in mm, `.scad` with minimal inputs, then gate checks (mesh, bbox, volume, overhang) plus an adversarial review. |
| [`skills/pr-opener`](skills/pr-opener/) | Opens a PR: verifies work, drafts title/body from the diff vs base, pushes, creates a draft PR (forge-agnostic: gh/tea/glab/Forgejo). |
| [`skills/screencapture`](skills/screencapture/) | Captures desktop/web screenshots and scripted videos/GIFs (terminal, web, desktop) on Linux, macOS and Windows. |
| [`skills/storyboard-video`](skills/storyboard-video/) | Workflow for the storyboard-video MCP: honest storyboard from the code, review stills, render, verify. |
| [`skills/svg-generator`](skills/svg-generator/) | Hand-writes SVG markup in a write, render, self-evaluate, revise loop. |
| [`skills/tech-blog-post`](skills/tech-blog-post/) | Writes a technical blog post (raw Markdown with frontmatter for Astro/Hugo) from something you actually did, in a direct, opinionated senior-dev voice. |
| [`skills/ui-review`](skills/ui-review/) | Full multi-agent web UI review (UX, visual, a11y, responsiveness) consolidated into one prioritized P0-P3 report. |
| [`skills/wiki-writing`](skills/wiki-writing/) | Writes or audits dense, verified technical wiki pages (reference, explanation, runbook, ADR, postmortem) with a numbers-consistency check and an independent review. |

Some skills (`guided-build`) also expect the [ponytail](https://github.com/DietrichGebert/ponytail) plugin, installed separately.

## Configuration and requirements

- **Docker** — every MCP server runs as a container; nothing else is needed to talk to it.
- **Python 3.9+** — the plugin entries start `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lazy-mcp.py`, the stdlib-only shim (no packages, no virtualenv).
- **Config files** — `actual-budget`, `woodpecker`, `vikunja` and `whatsapp` read a JSON file from `~/.config/llm-toolbox/<server>.json` (`config.example.json` in each server directory is the template; the files are mounted read-only). `document-ocr` reads documents from `~/.config/llm-toolbox/whatsapp-downloads`, `whatsapp` sends files from `~/.config/llm-toolbox/whatsapp-media`, and `audio-transcribe` mounts `$HOME` read-only instead of taking a config.

Setup steps, per-client instructions and the manual JSON are in [INSTALL.md](INSTALL.md).

## Resource usage and lazy loading

Idle MCP servers are the main cost of a toolbox like this (one container per server per session), so every entry in `.claude-plugin/plugin.json` runs through `scripts/lazy-mcp.py`:

- `/mcp` still lists the server as connected and shows its tools immediately: `initialize`, `tools/list`, `resources/list`, `prompts/list` and `ping` are answered from a cache written by an earlier run. No container starts for them.
- The first request that needs the real server (usually `tools/call`) spawns it, and the tool list is re-read; if the image changed its tool list, the cache is rewritten and `notifications/tools/list_changed` is sent.
- The container is stopped again after it goes idle: no request in flight and no traffic for `LAZY_MCP_IDLE_SECONDS` (default `600`, i.e. 10 minutes; `0` disables the idle stop).
- The first call of a session pays the `docker run`, including a `docker pull` when the image tag is not local yet. If a client times out on that call (Claude Code's `MCP_TIMEOUT`), raise it or pull the image up front with `docker pull harbor.bzd.gg/bzd/<image>:<version>`.
- Environment variables: `LAZY_MCP_IDLE_SECONDS` as above, and `LAZY_MCP_CACHE_DIR` to move the cache (default `${XDG_CACHE_HOME:-~/.cache}/llm-toolbox/lazy-mcp`, one `<entry>-<image tag>.json` file per server, mode `0600`).
- Refresh the cache by deleting that directory, or by regenerating one entry: `python3 scripts/lazy-mcp.py --name <entry> --refresh -- docker run -i --rm <image>:<version>`.
- `whatsapp` sets `LAZY_MCP_IDLE_SECONDS=0`: its pairing session degrades when the container is restarted, so it is never idle-killed.
- Pi does not use the shim at all: `pi-mcp.json` holds the plain `docker run` command and the Pi adapter is already lazy by itself.

## Development

```bash
# validate the plugin layout, the `-exec` invariant and the README coverage (stdlib only)
python3 scripts/validate-plugin.py

# version/derived-file checks; `sync` rewrites, `amend` bumps from the commit message (post-commit hook)
python3 scripts/release.py check

# the shim's test suite (< 30 s, fakes docker with a stdlib MCP server)
python3 scripts/test_lazy_mcp.py
python3 scripts/test_validate_plugin.py

# per-server tests
cd servers/storyboard-video && python -m pytest -q tests
cd servers/whatsapp && for t in tests/test_*.py; do python "$t" || exit 1; done

# build one image
docker build -t harbor.bzd.gg/bzd/<image>:<version> servers/<server>
```

Server, skill, plugin and package versions are linked: `servers/*/pyproject.toml` (server) and `skills/*/SKILL.md` `metadata.version` (skill) are the sources of truth, and `scripts/release.py` derives the image pins in `plugin.json`, the README version cells, `pi-mcp.json`, the plugin/marketplace/package versions and the image tags in `.woodpecker/build.yaml`. Do not hand-edit those.

## Security

- Every mount is read-only unless the server has to write: config files, `$HOME` (`audio-transcribe`), the storyboard repo, music and sound effects, WhatsApp media. The only read-write mounts are the data volumes (`actual-budget-data`, `whatsapp-data`, `storyboard-video-work`), the Hugging Face model cache, and the WhatsApp download root.
- `document-ocr` runs with `--network none` and `--group-add 1000`, and can only read paths under `~/.config/llm-toolbox/whatsapp-downloads`.
- `storyboard-video` runs hardened: `--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only` with `tmpfs` for `/tmp` and `/root`, `--pids-limit 256`, and the repo mounted read-only. The `storyboard-video-exec` twin adds `--cap-add SETGID`, drops the network entirely and only then allows command execution.
- `whatsapp` talks to WhatsApp Web, an unofficial protocol: pairing a number carries a real ban risk, and the `whatsapp-data` volume is a full login. Sending tools do not even exist unless you set `allow_send` (default `false`). Read the [honest limits](servers/whatsapp/README.md#honest-limits) before pairing.
- MCP servers get no host secrets beyond the config files you mount; nothing in this repo ships credentials.

## License

MIT — see [LICENSE](LICENSE).
