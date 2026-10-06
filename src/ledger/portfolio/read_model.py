"""Shared filtered read model for portfolio API and server-rendered pages."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from flask import current_app, has_app_context
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.db.models.catalog import Product
from ledger.db.models.portfolio import BankAccount, Position
from ledger.db.models.valuation import PositionSnapshot, ValuationRun


def rows(db: Session, user_id: uuid.UUID, filters: dict[str, str]) -> list[dict[str, Any]]:
    stmt = (
        select(Position, Product, BankAccount)
        .join(Product, Product.id == Position.product_id)
        .join(BankAccount, BankAccount.id == Position.account_id)
        .where(Position.user_id == user_id, BankAccount.user_id == user_id)
    )
    if filters.get("account_id"):
        stmt = stmt.where(Position.account_id == uuid.UUID(filters["account_id"]))
    if filters.get("bank_id"):
        stmt = stmt.where(BankAccount.bank_id == uuid.UUID(filters["bank_id"]))
    if filters.get("currency"):
        stmt = stmt.where(Product.currency == filters["currency"])
    status = filters.get("status", "holding")
    if status not in {"holding", "closed", "all"}:
        raise ValueError("invalid_position_status")
    if status == "holding":
        stmt = stmt.where(Position.shares > 0)
    elif status == "closed":
        stmt = stmt.where(Position.shares == 0)
    run = db.scalar(
        select(ValuationRun).where(
            ValuationRun.user_id == user_id, ValuationRun.is_current.is_(True)
        )
    )
    latest_run = db.scalar(
        select(ValuationRun)
        .where(ValuationRun.user_id == user_id)
        .order_by(ValuationRun.created_at.desc(), ValuationRun.id.desc())
        .limit(1)
    )
    pending_update = bool(
        run and latest_run and latest_run.id != run.id and latest_run.created_at > run.created_at
    )
    metrics_enabled = (
        not has_app_context() or current_app.config["LEDGER_SETTINGS"].metrics_v2_enabled
    )
    output: list[dict[str, Any]] = []
    for position, product, account in db.execute(stmt):
        snapshot = None
        if run:
            snapshot = db.scalar(
                select(PositionSnapshot)
                .where(
                    PositionSnapshot.user_id == user_id,
                    PositionSnapshot.run_id == run.id,
                    PositionSnapshot.account_id == account.id,
                    PositionSnapshot.product_id == product.id,
                )
                .order_by(PositionSnapshot.date.desc())
                .limit(1)
            )
        if pending_update or not metrics_enabled:
            snapshot = None
        metrics = (
            snapshot.metrics
            if snapshot and run and run.formula_version == "v2"
            else {"quality": "missing", "reason": "valuation_required"}
        )
        market = snapshot.market_value if snapshot else None
        unrealized = snapshot.unrealized_pnl if snapshot else None
        output.append(
            {
                "id": str(position.id),
                "account_id": str(account.id),
                "product_id": str(product.id),
                "product_name": product.name,
                "product_code": product.issuer_code,
                "bank_id": str(account.bank_id),
                "account_name": account.alias,
                "currency": product.currency,
                "shares": str(position.shares),
                "remaining_cost": str(position.remaining_cost),
                "realized_pnl": str(position.realized_pnl),
                "ledger_version": position.ledger_version,
                "last_transaction_date": position.last_transaction_date.isoformat()
                if position.last_transaction_date
                else None,
                "created_at": position.created_at.isoformat(),
                "updated_at": position.updated_at.isoformat(),
                "market_value": str(market) if market is not None else None,
                "unrealized_pnl": str(unrealized) if unrealized is not None else None,
                "metrics": metrics,
                "valuation_date": snapshot.date.isoformat() if snapshot else None,
                "run_id": str(run.id) if run else None,
            }
        )
    sort = filters.get("sort", "market_value")
    allowed = {
        "market_value",
        "holding_annualized_return",
        "latest_income",
        "latest_income_per_10k_value",
    }
    if sort not in allowed:
        raise ValueError("invalid_sort")

    def key(item: dict[str, Any]) -> tuple[bool, Decimal]:
        value = item.get(sort) if sort == "market_value" else item["metrics"].get(sort)
        return value is None, -Decimal(str(value)) if value is not None else Decimal(0)

    return sorted(output, key=key)


def summarize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for currency in sorted({item["currency"] for item in items}):
        group = [item for item in items if item["currency"] == currency]
        market_values = [item["market_value"] for item in group]
        complete = all(value is not None for value in market_values)
        metrics = [item["metrics"] for item in group]
        incomes = [m.get("latest_income") for m in metrics]
        periods = {(m.get("interval_start"), m.get("interval_end")) for m in metrics}
        nav_dates = {m.get("nav_date") for m in metrics}
        annualized = None
        pnl_values = [m.get("holding_pnl") for m in metrics]
        if len(nav_dates) == 1 and all(
            m.get("holding_annualized_return") is not None for m in metrics
        ):
            capital = sum((Decimal(str(m["capital_days"])) for m in metrics), Decimal(0))
            if capital > 0:
                annualized = str(
                    sum((Decimal(str(p)) for p in pnl_values), Decimal(0)) * 365 / capital
                )
        tenk = None
        if len(periods) == 1 and all(
            not m.get("has_cashflows") and m.get("latest_income_per_10k_value") is not None
            for m in metrics
        ):
            total = sum((Decimal(str(m["beginning_market_value"])) for m in metrics), Decimal(0))
            if total > 0:
                tenk = str(
                    sum(
                        (
                            Decimal(str(m["beginning_market_value"]))
                            * Decimal(str(m["latest_income_per_10k_value"]))
                            for m in metrics
                        ),
                        Decimal(0),
                    )
                    / total
                )
        result.append(
            {
                "currency": currency,
                "position_count": len(group),
                "market_value": str(sum((Decimal(str(v)) for v in market_values), Decimal(0)))
                if complete
                else None,
                "holding_pnl": str(sum((Decimal(str(v)) for v in pnl_values), Decimal(0)))
                if all(v is not None for v in pnl_values)
                else None,
                "latest_income": str(sum((Decimal(str(v)) for v in incomes), Decimal(0)))
                if all(v is not None for v in incomes)
                else None,
                "holding_annualized_return": annualized,
                "latest_income_per_10k_value": tenk,
                "mixed_dates": len(periods) != 1,
                "intervals": [list(p) for p in sorted(periods, key=str)],
                "quality": "complete"
                if complete and all(m.get("quality") == "complete" for m in metrics)
                else "partial",
            }
        )
    return result
