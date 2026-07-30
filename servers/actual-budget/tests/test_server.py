import asyncio

from actual_budget_mcp.server import mcp

EXPECTED_TOOLS = {
    "list_accounts",
    "list_categories",
    "list_transactions",
    "get_budget_amount",
    "create_new_transaction",
    "update_existing_transaction",
    "set_category_budget_amount",
    "mark_transaction_transfer",
    "create_payee_rule",
}


def test_tools_registered():
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS, names


if __name__ == "__main__":
    test_tools_registered()
    print("ok")
