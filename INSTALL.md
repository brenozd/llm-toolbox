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
ln -s "$(pwd)/skills/bug-sweep" ~/.claude/skills/bug-sweep

# one project only
ln -s "$(pwd)/skills/bug-sweep" /path/to/project/.claude/skills/bug-sweep
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

## Other SKILL.md-compatible agents

Cursor, Codex CLI, and VS Code Copilot also read `SKILL.md` unmodified —
symlink into whichever skills directory each tool documents, or into the
shared `.agents/skills/` path above.

## MCP servers

The plugin (`/plugin install llm-toolbox@llm-toolbox`) registers both
`actual-budget` and `woodpecker` MCPs automatically — no need to hand-copy
JSON. Each still needs its own `config.json` (see
[`servers/actual-budget/README.md`](servers/actual-budget/README.md#config)
and [`servers/woodpecker/README.md`](servers/woodpecker/README.md#config))
and an env var pointing to it, set before Claude Code starts:

```bash
export ACTUAL_BUDGET_MCP_CONFIG=/path/to/actual-budget-config.json
export WOODPECKER_MCP_CONFIG=/path/to/woodpecker-config.json
```

Without these set, the servers still start but the docker run fails to
mount a config file, so their tools won't appear — check `/mcp` in Claude
Code to confirm both are connected. Skip an unused server's env var if you
don't need it; that server just won't come up.

For a non-plugin client (Claude Desktop, Gemini CLI, etc), register
manually with the JSON in each server's README under `## Run` instead.
