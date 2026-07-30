from __future__ import annotations

import datetime

from sqlmodel import Session

from actual import Actual
from actual.database import Transactions
from actual.exceptions import ActualError
from actual.queries import (
    create_budget,
    create_rule as _create_rule,
    create_transaction,
    get_account,
    get_accounts,
    get_budget,
    get_categories,
    get_category,
    get_or_create_category,
    get_transactions,
    set_transaction_payee,
)
from actual.rules import Action, Condition, ConditionType, Rule, ValueType
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


def mark_transaction_transfer(actual: Actual, transaction_id: str, counterpart_transaction_id: str) -> dict:
    """Link two existing transactions (one per account) as a transfer pair, clearing their category."""
    session = actual.session
    txn = session.get(Transactions, transaction_id)
    other = session.get(Transactions, counterpart_transaction_id)
    if txn is None:
        raise ActualError(f"Transaction '{transaction_id}' not found")
    if other is None:
        raise ActualError(f"Transaction '{counterpart_transaction_id}' not found")
    if txn.acct == other.acct:
        raise ActualError("Transactions must belong to different accounts to form a transfer")
    txn_account = get_account(session, txn.acct)
    other_account = get_account(session, other.acct)
    set_transaction_payee(session, txn, other_account.payee)
    set_transaction_payee(session, other, txn_account.payee)
    txn.transferred_id = other.id
    other.transferred_id = txn.id
    txn.category_id = None
    other.category_id = None
    actual.commit()
    return {"transaction": transaction_to_dict(txn), "counterpart": transaction_to_dict(other)}


def create_payee_rule(actual: Actual, contains: str, category: str, run_immediately: bool = True) -> dict:
    """Create a rule that sets `category` on any transaction whose imported bank description contains `contains`."""
    resolved_category = get_or_create_category(actual.session, category)
    rule = Rule(
        conditions=[
            Condition(field="imported_description", op=ConditionType.CONTAINS, value=contains, type=ValueType.STRING)
        ],
        actions=[Action(field="category", value=resolved_category.id)],
    )
    database_rule = _create_rule(actual.session, rule, run_immediately=run_immediately)
    actual.commit()
    return {
        "rule_id": database_rule.id,
        "contains": contains,
        "category": resolved_category.name,
        "run_immediately": run_immediately,
    }
