from __future__ import annotations

import datetime
import decimal

from actual.database import Accounts, Categories, Transactions
from actual.database import BaseBudgets


def _money(amount: decimal.Decimal | int | float | None) -> float | None:
    return float(amount) if amount is not None else None


def account_to_dict(a: Accounts) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "balance": _money(a.balance),
        "offbudget": bool(a.offbudget),
        "closed": bool(a.closed),
    }


def category_to_dict(c: Categories) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "group_id": c.cat_group,
        "is_income": bool(c.is_income),
        "hidden": bool(c.hidden),
    }


def transaction_to_dict(t: Transactions) -> dict:
    return {
        "id": t.id,
        "account_id": t.acct,
        "account_name": t.account.name if t.account else None,
        "date": t.get_date().isoformat(),
        "amount": _money(t.get_amount()),
        "payee": t.payee.name if t.payee else None,
        "category_id": t.category_id,
        "category_name": t.category.name if t.category else None,
        "notes": t.notes,
        "cleared": bool(t.cleared),
    }


def budget_to_dict(b: BaseBudgets, month: datetime.date, category_name: str | None) -> dict:
    return {
        "month": month.strftime("%Y-%m"),
        "category_id": b.category_id if b else None,
        "category_name": category_name,
        "budgeted": _money(b.get_amount()) if b else 0.0,
    }
