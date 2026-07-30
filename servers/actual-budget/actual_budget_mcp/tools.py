from __future__ import annotations

import datetime

from sqlmodel import Session

from actual import Actual
from actual.database import Transactions
from actual.exceptions import ActualError
from actual.queries import (
    create_budget,
    create_transaction,
    get_accounts,
    get_budget,
    get_categories,
    get_category,
    get_or_create_category,
    get_transactions,
    set_transaction_payee,
)
from actual.utils.conversions import decimal_to_cents

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


def create_new_transaction(
    actual: Actual,
    account: str,
    date: str,
    amount: float,
    payee: str | None = None,
    category: str | None = None,
    notes: str | None = None,
    cleared: bool = False,
) -> dict:
    transaction = create_transaction(
        actual.session,
        datetime.date.fromisoformat(date),
        account,
        payee=payee,
        notes=notes,
        category=category,
        amount=amount,
        cleared=cleared,
    )
    actual.commit()
    return transaction_to_dict(transaction)


def update_existing_transaction(
    actual: Actual,
    transaction_id: str,
    payee: str | None = None,
    category: str | None = None,
    amount: float | None = None,
    notes: str | None = None,
    cleared: bool | None = None,
) -> dict:
    session = actual.session
    transaction = session.get(Transactions, transaction_id)
    if transaction is None:
        raise ActualError(f"Transaction '{transaction_id}' not found")
    if payee is not None:
        set_transaction_payee(session, transaction, payee)
    if category is not None:
        transaction.category_id = get_or_create_category(session, category).id
    if amount is not None:
        transaction.amount = decimal_to_cents(amount)
    if notes is not None:
        transaction.notes = notes
    if cleared is not None:
        transaction.cleared = int(cleared)
    actual.commit()
    return transaction_to_dict(transaction)


def set_category_budget_amount(actual: Actual, month: str, category: str, amount: float) -> dict:
    month_date = datetime.date.fromisoformat(f"{month}-01")
    resolved_category = get_or_create_category(actual.session, category)
    budget = create_budget(actual.session, month_date, resolved_category, amount)
    actual.commit()
    return budget_to_dict(budget, month_date, resolved_category.name)
