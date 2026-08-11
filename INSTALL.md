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
ln -s "$(pwd)/skills/caveman-sweep" ~/.claude/skills/caveman-sweep

# one project only
ln -s "$(pwd)/skills/caveman-sweep" /path/to/project/.claude/skills/caveman-sweep
```

Some skills (`caveman-sweep`, `guided-build`) expect the
[caveman](https://github.com/JuliusBrussee/caveman) and
[ponytail](https://github.com/DietrichGebert/ponytail) plugins — install
those separately per their own docs.

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

See [`servers/actual-budget/README.md`](servers/actual-budget/README.md#run)
for the `mcpServers` JSON to register that server with an MCP client
(Claude Code, Claude Desktop, Gemini CLI, etc). The same
`docker run -i --rm ...`-spawned-by-the-client pattern applies to any future
server added under `servers/`.
