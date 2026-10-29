# Install

## Claude Code

Recommended — add this repo as a plugin marketplace, then install the
plugin (pulls all skills at once, updates with `/plugin marketplace update`):

```
/plugin marketplace add https://git.bzd.gg/bzd/llm-toolbox.git
/plugin install llm-toolbox@llm-toolbox
```

(`owner/repo` shorthand only work for github.com — self-hosted Forgejo need full clone URL.)

Local checkout instead of a remote add:

```
/plugin marketplace add /path/to/llm-toolbox
/plugin install llm-toolbox@llm-toolbox
```

Manual alternative — symlink individual skills instead of the whole plugin:

```bash
# all projects
ln -s "$(pwd)/skills/screenshot" ~/.claude/skills/screenshot

# one project only
ln -s "$(pwd)/skills/screenshot" /path/to/project/.claude/skills/screenshot
```

Some skills (`guided-build`) expect the
[ponytail](https://github.com/DietrichGebert/ponytail) plugin — install
it separately per its own docs.

## Gemini CLI

Gemini CLI reads the same `SKILL.md` format natively. Symlink or copy the
same skill directories:

```bash
# user-wide
ln -s "$(pwd)/skills/screenshot" ~/.gemini/skills/screenshot

# workspace only
ln -s "$(pwd)/skills/screenshot" /path/to/project/.gemini/skills/screenshot
```

To share one copy across Gemini CLI, Cursor, and Codex CLI, symlink into
`.agents/skills/` (or `~/.agents/skills/`) instead — that path is an
emerging cross-tool convention those agents also read. Claude Code does not
read `.agents/skills/` yet, so use the Claude Code steps above for that tool.

## Pi

[Pi](https://pi.dev) discovers pi-packages via `package.json`'s `pi.skills` field —
this repo already declares one, so a plain package install pulls all skills:

```
pi install git:git.bzd.gg/bzd/llm-toolbox
```

Or from a local checkout:

```
pi install /path/to/llm-toolbox
```

`pi list` confirms it's registered; `pi remove git:git.bzd.gg/bzd/llm-toolbox`
uninstalls it. The MCP servers are a Claude Code plugin feature with no Pi
package equivalent — only the skills install under Pi.

## Other SKILL.md-compatible agents

Cursor, Codex CLI, and VS Code Copilot also read `SKILL.md` unmodified —
symlink into whichever skills directory each tool documents, or into the
shared `.agents/skills/` path above.

## MCP servers

The plugin (`/plugin install llm-toolbox@llm-toolbox`) registers
`actual-budget`, `woodpecker`, `vikunja`, `faster-whisper`, `promo-video`, `promo-video-exec`, and `whatsapp` MCPs automatically — no
need to hand-copy JSON. `actual-budget`, `woodpecker`, `vikunja` and `whatsapp` each need their own
`config.json` (see
[`servers/actual-budget/README.md`](servers/actual-budget/README.md#config)
and [`servers/woodpecker/README.md`](servers/woodpecker/README.md#config))
dropped at a fixed path, no env vars needed:

```bash
mkdir -p ~/.config/llm-toolbox
cp servers/actual-budget/config.example.json ~/.config/llm-toolbox/actual-budget.json
cp servers/woodpecker/config.example.json ~/.config/llm-toolbox/woodpecker.json
cp servers/vikunja/config.example.json ~/.config/llm-toolbox/vikunja.json
cp servers/whatsapp/config.example.json ~/.config/llm-toolbox/whatsapp.json
# then edit them with your real server details
```

Without the file at that path, the server still starts but its `docker run`
fails to mount a config, so its tools won't appear — check `/mcp` in Claude
Code to confirm they are connected. Skip a file for a server you don't need;
that one just won't come up.

`faster-whisper` needs no config file — it mounts your home directory
read-only instead, and is tuned with env vars if needed (see
[`servers/faster-whisper/README.md`](servers/faster-whisper/README.md#config)).

`whatsapp` also needs a one-time QR pairing (`docker run -it ... login`, see
[`servers/whatsapp/README.md`](servers/whatsapp/README.md#login)), keeps its
session in the `whatsapp-data` volume, and mounts `~/.config/llm-toolbox/whatsapp-media`
read-only as the only folder files can be sent from (`mkdir` it first).
Sending is off unless you set `allow_send` in its config. It talks to WhatsApp
Web, an unofficial protocol: pairing a number carries a real ban risk, and the
session volume is a full login — see the
[honest limits](servers/whatsapp/README.md#honest-limits) before pairing.

For a non-plugin client (Claude Desktop, Gemini CLI, etc), register
manually with the JSON in each server's README under `## Run` instead.
