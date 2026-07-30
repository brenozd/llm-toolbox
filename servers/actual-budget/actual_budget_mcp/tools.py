from __future__ import annotations

import datetime

from sqlmodel import Session

from actual.queries import get_accounts, get_budget, get_categories, get_category, get_transactions

from .serialize import account_to_dict, budget_to_dict, category_to_dict, transaction_to_dict


def list_accounts(session: Session) -> list[dict]:
    return [account_to_dict(a) for a in get_accounts(session)]


def list_categories(session: Session) -> list[dict]:
    return [category_to_dict(c) for c in get_categories(session)]


def list_transactions(
    session: Session,
    account: str | None = None,
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    start = datetime.date.fromisoformat(start_date) if start_date else None
    end = datetime.date.fromisoformat(end_date) if end_date else None
    transactions = get_transactions(session, start_date=start, end_date=end, account=account, category=category)
    return [transaction_to_dict(t) for t in transactions]


def get_budget_amount(session: Session, month: str, category: str) -> dict:
    month_date = datetime.date.fromisoformat(f"{month}-01")
    budget = get_budget(session, month_date, category)
    resolved_category = get_category(session, category)
    category_name = resolved_category.name if resolved_category else category
    return budget_to_dict(budget, month_date, category_name)
