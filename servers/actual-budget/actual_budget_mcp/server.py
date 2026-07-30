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


def _actual(ctx: Context) -> Actual:
    return ctx.request_context.lifespan_context


def _session(ctx: Context):
    return _actual(ctx).session


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


@mcp.tool()
def create_new_transaction(
    ctx: Context,
    account: str,
    date: str,
    amount: float,
    payee: str | None = None,
    category: str | None = None,
    notes: str | None = None,
    cleared: bool = False,
) -> dict:
    """Create a transaction (date as YYYY-MM-DD, amount positive for deposits, negative for payments)."""
    return t.create_new_transaction(_actual(ctx), account, date, amount, payee, category, notes, cleared)


@mcp.tool()
def update_existing_transaction(
    ctx: Context,
    transaction_id: str,
    payee: str | None = None,
    category: str | None = None,
    amount: float | None = None,
    notes: str | None = None,
    cleared: bool | None = None,
) -> dict:
    """Update fields on an existing transaction by id. Only provided fields are changed."""
    return t.update_existing_transaction(_actual(ctx), transaction_id, payee, category, amount, notes, cleared)


@mcp.tool()
def set_category_budget_amount(ctx: Context, month: str, category: str, amount: float) -> dict:
    """Set the budgeted amount for a category in a given month (month as YYYY-MM). Creates the category if missing."""
    return t.set_category_budget_amount(_actual(ctx), month, category, amount)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
