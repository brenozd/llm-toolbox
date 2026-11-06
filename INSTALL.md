# Install

## Requirements

- **Docker** — the MCP servers run as containers from `harbor.bzd.gg/bzd/*`; nothing is built locally, the image is pulled on first use.
- **python3** (3.9+) — the plugin starts every server through `scripts/lazy-mcp.py`, a stdlib-only shim: no packages, no virtualenv, no `pip install`.
- Skills, agents and extensions need neither: they are Markdown and JS files the agent reads.

## Claude Code

Recommended — add this repo as a plugin marketplace, then install the
plugin (pulls all skills at once, updates with `/plugin marketplace update`):

```
/plugin marketplace add https://github.com/brenozd/llm-toolbox.git
/plugin install llm-toolbox@llm-toolbox
```

(`owner/repo` shorthand also works here, since the repo lives on github.com.)

Local checkout instead of a remote add:

```
/plugin marketplace add /path/to/llm-toolbox
/plugin install llm-toolbox@llm-toolbox
```

Manual alternative — symlink individual skills instead of the whole plugin:

```bash
# all projects
ln -s "$(pwd)/skills/screencapture" ~/.claude/skills/screencapture

# one project only
ln -s "$(pwd)/skills/screencapture" /path/to/project/.claude/skills/screencapture
```

Some skills (`guided-build`) expect the
[ponytail](https://github.com/DietrichGebert/ponytail) plugin — install
it separately per its own docs.

## Gemini CLI

Gemini CLI reads the same `SKILL.md` format natively. Symlink or copy the
same skill directories:

```bash
# user-wide
ln -s "$(pwd)/skills/screencapture" ~/.gemini/skills/screencapture

# workspace only
ln -s "$(pwd)/skills/screencapture" /path/to/project/.gemini/skills/screencapture
```

To share one copy across Gemini CLI, Cursor, and Codex CLI, symlink into
`.agents/skills/` (or `~/.agents/skills/`) instead — that path is an
emerging cross-tool convention those agents also read. Claude Code does not
read `.agents/skills/` yet, so use the Claude Code steps above for that tool.

## Pi

[Pi](https://pi.dev) discovers pi-packages via `package.json`'s `pi.skills` field —
this repo already declares one, so a plain package install pulls all skills:

```
pi install git:github.com/brenozd/llm-toolbox
```

Or from a local checkout:

```
pi install /path/to/llm-toolbox
```

`pi list` confirms it's registered; `pi remove git:github.com/brenozd/llm-toolbox`
uninstalls it. The MCP servers come from `pi-mcp.json` (`pi.mcp` in `package.json`), which
needs the [pi-mcp-adapter](https://github.com/nicobailon/pi-mcp-adapter) extension and Docker;
they show up as `llm-toolbox__<server>`. `pi-mcp.json` is generated from the unwrapped `docker run`
command in `.claude-plugin/plugin.json` by `scripts/release.py` (pre-commit hook), so edit the
plugin file only. Pi does not go through the lazy shim: its adapter is already lazy by itself, so
`pi-mcp.json` stays a plain `docker run` command.

## Other SKILL.md-compatible agents

Cursor, Codex CLI, and VS Code Copilot also read `SKILL.md` unmodified —
symlink into whichever skills directory each tool documents, or into the
shared `.agents/skills/` path above.

## MCP servers

The plugin (`/plugin install llm-toolbox@llm-toolbox`) registers
`actual-budget`, `woodpecker`, `vikunja`, `audio-transcribe`, `storyboard-video`, `storyboard-video-exec`, `document-ocr`, and `whatsapp` MCPs automatically — no
need to hand-copy JSON. `actual-budget`, `woodpecker`, `vikunja` and `whatsapp` each need their own
`config.json` (see
[`servers/actual-budget/README.md`](servers/actual-budget/README.md#config)
and [`servers/woodpecker/README.md`](servers/woodpecker/README.md#config))
dropped at a fixed path — there is no config environment variable to set (the
lazy-loading knobs below are the only ones):

```bash
mkdir -p ~/.config/llm-toolbox
mkdir -p ~/.config/llm-toolbox/whatsapp-downloads   # document-ocr reads documents from here
cp servers/actual-budget/config.example.json ~/.config/llm-toolbox/actual-budget.json
cp servers/woodpecker/config.example.json ~/.config/llm-toolbox/woodpecker.json
cp servers/vikunja/config.example.json ~/.config/llm-toolbox/vikunja.json
cp servers/whatsapp/config.example.json ~/.config/llm-toolbox/whatsapp.json
# then edit them with your real server details
```

Without the file at that path the server fails at startup with a config error, so every call
comes back as an error carrying the server's stderr — `/mcp` can still list the tools, because the
lazy shim answers it from its cache, so do not read `/mcp` as proof that a config loaded. Skip a
file for a server you don't need; that one just won't work when called.

`audio-transcribe` needs no config file — it mounts your home directory
read-only instead, and is tuned with env vars if needed (see
[`servers/audio-transcribe/README.md`](servers/audio-transcribe/README.md#config)).

`document-ocr` needs no config file either, but it only reads documents inside
`~/.config/llm-toolbox/whatsapp-downloads` (the folder the `whatsapp` server
downloads media to), mounted read-only — `mkdir -p` it first, see
[`servers/document-ocr/README.md`](servers/document-ocr/README.md).

`whatsapp` also needs a one-time QR pairing (`docker run -it ... login`, see
[`servers/whatsapp/README.md`](servers/whatsapp/README.md#login)), keeps its
session in the `whatsapp-data` volume, and mounts `~/.config/llm-toolbox/whatsapp-media`
read-only as the only folder files can be sent from (`mkdir` it first).
Sending is off unless you set `allow_send` in its config. It talks to WhatsApp
Web, an unofficial protocol: pairing a number carries a real ban risk, and the
session volume is a full login — see the
[honest limits](servers/whatsapp/README.md#honest-limits) before pairing.

For a non-plugin client, register manually with the JSON in each server's README
under `## Run` instead — see [Other clients](#other-clients) below.

### Lazy loading

Each entry in `.claude-plugin/plugin.json` runs
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lazy-mcp.py --name <entry> -- docker run ...`, so the
container stays stopped until a tool is actually called:

- `/mcp` lists every server as connected without starting anything: `initialize`, the `*/list`
calls and `ping` are answered from a cache written by an earlier run. The very first session has
no cache yet, so it starts the container once to write it.
- The first request that needs the real server (usually a tool call) pays `docker run`, plus
`docker pull` when that tag is not local. A client-side timeout on that call is usually the pull:
raise `MCP_TIMEOUT` in Claude Code, or `docker pull harbor.bzd.gg/bzd/<image>:<version>` first.
- `LAZY_MCP_IDLE_SECONDS` — stop the container after this much idle time; default `600` (10
minutes), `0` never idle-stops.
- `LAZY_MCP_CACHE_DIR` — where the cache lives; default
`${XDG_CACHE_HOME:-~/.cache}/llm-toolbox/lazy-mcp`, one `<entry>-<image tag>.json` per server
(mode `0600`), tagged by image version, so a bumped image gets its own file.
- Refresh the cache by deleting that directory, or regenerate a single entry:
`python3 scripts/lazy-mcp.py --name <entry> --refresh -- docker run -i --rm <image>:<version>`.
- `whatsapp` sets `LAZY_MCP_IDLE_SECONDS=0`: its pairing session degrades when the container is
restarted, so it is never idle-killed.

### Other clients

The plugin install above is the only path that gets lazy loading. Gemini CLI, Codex CLI, Claude
Desktop and other MCP clients register servers with the JSON in each server's README under
`## Run`, which stays a direct `docker run`: the container starts as soon as the client connects
and runs for the whole session. To opt in to lazy loading there, run the shim you already have on
disk as a prefix — everything after `--` is the server command, unchanged:

```json
{
  "command": "python3",
  "args": [
    "/path/to/llm-toolbox/scripts/lazy-mcp.py", "--name", "vikunja", "--",
    "docker", "run", "-i", "--rm",
    "-v", "/home/you/.config/llm-toolbox/vikunja.json:/config/config.json:ro",
    "harbor.bzd.gg/bzd/vikunja-mcp:0.1.0"
  ]
}
```

Those clients do not expand `${HOME}`/`${PWD}` for you, so write the absolute paths out (the same
reason `pi-mcp.json` wraps `docker run` in `sh -c`).
`--name` only labels the cache file and the container; the same env vars
(`LAZY_MCP_IDLE_SECONDS`, `LAZY_MCP_CACHE_DIR`) apply.
