# vikunja-mcp

MCP server for [Vikunja](https://vikunja.io): projects, tasks, comments and
labels over stdio, through the REST API (`/api/v1`).

Reads cover projects, tasks (with Vikunja filter syntax), comments and labels.
Writes are limited to creating/updating tasks (including `done`), adding
comments and attaching existing labels. There is no delete anywhere, and no
project, user, sharing or webhook management.

## Config

Copy `config.example.json` to `~/.config/llm-toolbox/vikunja.json` and mount
it read-only at `/config/config.json`:

```json
{
  "base_url": "https://vikunja.example.com",
  "token": "your-api-token"
}
```

Create the token under Settings → API Tokens in Vikunja and grant only the
permissions you need (for read-only use, only the `get`/`list` ones). The
token is the only access control: the server does not restrict what it can do.

## Tools

| Tool | Purpose |
|---|---|
| `vikunja_projects` | list/search projects or get one |
| `vikunja_tasks` | list tasks (all or per project), `search`, `filter`, paging |
| `vikunja_task` | get a task |
| `vikunja_comments` / `vikunja_add_comment` | read / add comments |
| `vikunja_labels` / `vikunja_add_label` | list labels / attach one to a task |
| `vikunja_create_task` / `vikunja_update_task` | create / edit (omitted fields are kept) |

Task text and comments are third-party data; tool descriptions tell the model
not to follow instructions inside them. That reduces prompt injection but does
not eliminate it, so use a token scoped to what the agent needs.

## Run

```bash
docker run -i --rm -v ~/.config/llm-toolbox/vikunja.json:/config/config.json:ro \
  harbor.bzd.gg/bzd/vikunja-mcp:latest
```

Tests (offline): `pip install . && for t in tests/test_*.py; do python $t; done`
