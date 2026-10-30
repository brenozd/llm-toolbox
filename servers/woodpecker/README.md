# woodpecker-mcp

MCP server for [Woodpecker CI/CD](https://woodpecker-ci.org) — orgs, repos,
pipelines, secrets, registries, cron jobs, agents, and users, over stdio.

Read coverage is broad (every practical `GET` route). Write coverage is
intentionally narrow: creating an organization secret and triggering a
pipeline run — no delete/update anywhere, no repo/global secret writes, no
admin endpoints (agents/forges/users/registries/cron mutation, repo
activate/move/chown).

## Config

Copy `config.example.json`, fill in your Woodpecker server URL and a
personal API token, and mount it read-only into the container at
`/config/config.json`:

```json
{
  "base_url": "https://woodpecker.bzd.gg",
  "token": "your-personal-api-token"
}
```

Get the token from your own Woodpecker account: profile → API/CLI tab, or
reset it via `POST /api/user/token`. There are no separate OAuth scopes —
the token carries whatever org/repo roles your account already has, so it
must be an admin/owner on any org where `woodpecker_create_org_secret` gets
used.

## Image

CI (`.woodpecker/`) builds and pushes this on every push to `master`
touching `servers/woodpecker/**`, and on `woodpecker-v*` tags:

```bash
docker pull harbor.bzd.gg/bzd/woodpecker-mcp:latest
```

To build locally instead:

```bash
docker build -t harbor.bzd.gg/bzd/woodpecker-mcp:latest .
```

## Run

The server speaks MCP over stdio, so it's meant to be spawned by an MCP
client (Claude Code, Claude Desktop, etc.), not left running standalone.
Register it with a command like:

```json
{
  "mcpServers": {
    "woodpecker": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/path/to/config.json:/config/config.json:ro",
        "harbor.bzd.gg/bzd/woodpecker-mcp:latest"
      ]
    }
  }
}
```

To try it by hand:

```bash
docker run -i --rm \
  -v $(pwd)/config.json:/config/config.json:ro \
  harbor.bzd.gg/bzd/woodpecker-mcp:latest
```

## Tools

| Tool | Description |
|---|---|
| `woodpecker_orgs` | List orgs, get one by id, or look one up by full name |
| `woodpecker_org_permissions` | Current user's permissions for an org |
| `woodpecker_org_secrets` | List an org's secrets, or get one by name |
| `woodpecker_org_registries` | List an org's registries, or get one by name |
| `woodpecker_repos` | List all repos, get one by id, or look one up by full name |
| `woodpecker_repo_branches` | Branches of a repo |
| `woodpecker_repo_permissions` | Current user's permissions for a repo |
| `woodpecker_repo_pull_requests` | Active pull requests of a repo |
| `woodpecker_repo_secrets` | List a repo's secrets, or get one by name |
| `woodpecker_repo_registries` | List a repo's registries, or get one by name |
| `woodpecker_repo_cron` | List a repo's cron jobs, or get one by name |
| `woodpecker_pipelines` | List a repo's pipelines, or get one by number |
| `woodpecker_pipeline_config` | Resolved config files for a pipeline run |
| `woodpecker_pipeline_metadata` | Metadata for a pipeline run |
| `woodpecker_pipeline_logs` | Logs for one step of a pipeline run |
| `woodpecker_queue_pipelines` | Pipelines currently in the run queue |
| `woodpecker_queue_info` | Queue statistics |
| `woodpecker_secrets` | List global secrets, or get one by name |
| `woodpecker_registries` | List global registries, or get one by name |
| `woodpecker_agents` | List agents, get one by id, or list an org's agents |
| `woodpecker_agent_tasks` | Tasks assigned to an agent |
| `woodpecker_forges` | List forges, or get one by id |
| `woodpecker_users` | List users, or get one by login |
| `woodpecker_user_self` | The currently authenticated user |
| `woodpecker_user_feed` | Current user's pipeline activity feed |
| `woodpecker_user_repos` | Repos the current user can access |
| `woodpecker_server_info` | Server version, health, signature public key |
| `woodpecker_create_org_secret` | Create an organization secret |
| `woodpecker_trigger_pipeline` | Manually trigger a pipeline run |

## Tests

```bash
pip install -e .
python tests/test_config.py
python tests/test_server.py
```

Both run offline — no Woodpecker server needed. To smoke-test against a
real server, point `WOODPECKER_MCP_CONFIG` at a real config file and run
`woodpecker-mcp`, then call `woodpecker_orgs` from an MCP client.
