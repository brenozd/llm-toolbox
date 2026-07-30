# actual-budget-mcp

MCP server for [Actual Budget](https://actualbudget.org) — accounts, transactions,
categories, and budgeted amounts, over stdio.

## Config

Copy `config.example.json`, fill in your Actual server details, and mount it
read-only into the container at `/config/config.json`:

```json
{
  "server_url": "http://host.docker.internal:5006",
  "password": "your-actual-server-password",
  "file": "your-budget-name-or-sync-id",
  "encryption_password": null,
  "data_dir": "/data"
}
```

`file` accepts the budget name, file id, or sync id — whichever uniquely
identifies it on the server. `encryption_password` is only needed if the
budget itself is end-to-end encrypted; omit or set to `null` otherwise.

`data_dir` (default `/data`) is where the local SQLite snapshot of the budget
is kept between runs — mount a volume there so restarts sync incrementally
instead of re-downloading the whole budget.

## Build

```bash
docker build -t actual-budget-mcp .
```

## Run

The server speaks MCP over stdio, so it's meant to be spawned by an MCP
client (Claude Code, Claude Desktop, etc.), not left running standalone.
Register it with a command like:

```json
{
  "mcpServers": {
    "actual-budget": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/path/to/config.json:/config/config.json:ro",
        "-v", "actual-budget-data:/data",
        "actual-budget-mcp"
      ]
    }
  }
}
```

To try it by hand:

```bash
docker run -i --rm \
  -v $(pwd)/config.json:/config/config.json:ro \
  -v actual-budget-data:/data \
  actual-budget-mcp
```

## Tools

| Tool | Description |
|---|---|
| `list_accounts` | All accounts with current balances |
| `list_categories` | All budget categories |
| `list_transactions` | Transactions, filterable by account, category, date range |
| `get_budget_amount` | Budgeted amount for a category in a given month |
| `create_new_transaction` | Create a transaction |
| `update_existing_transaction` | Update payee/category/amount/notes/cleared on a transaction |
| `set_category_budget_amount` | Set the budgeted amount for a category in a given month |

## Tests

```bash
pip install -e .
python tests/test_config.py
python tests/test_server.py
```

Both run offline — no Actual server needed. To smoke-test against a real
server, point `ACTUAL_MCP_CONFIG` at a real config file and run
`actual-budget-mcp`, then call `list_accounts` from an MCP client.
