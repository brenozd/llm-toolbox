from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP

from actual import Actual

from . import tools as t
from .client import open_actual
from .config import load_config


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[Actual]:
    config = load_config()
    with open_actual(config) as actual:
        yield actual


mcp = FastMCP("actual-budget", lifespan=lifespan)


def _session(ctx: Context):
    actual: Actual = ctx.request_context.lifespan_context
    return actual.session


@mcp.tool()
def list_accounts(ctx: Context) -> list[dict]:
    """List all budget accounts with their current balance."""
    return t.list_accounts(_session(ctx))


@mcp.tool()
def list_categories(ctx: Context) -> list[dict]:
    """List all budget categories."""
    return t.list_categories(_session(ctx))


@mcp.tool()
def list_transactions(
    ctx: Context,
    account: str | None = None,
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """List transactions, optionally filtered by account name/id, category name/id, and date range (YYYY-MM-DD, end exclusive)."""
    return t.list_transactions(_session(ctx), account, category, start_date, end_date)


@mcp.tool()
def get_budget_amount(ctx: Context, month: str, category: str) -> dict:
    """Get the budgeted amount for a category in a given month (month as YYYY-MM)."""
    return t.get_budget_amount(_session(ctx), month, category)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
