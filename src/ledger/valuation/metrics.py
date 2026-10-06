"""Auditable position metrics; all arithmetic stays in Decimal."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.db.models.catalog import Product, ValuationMethod
from ledger.db.models.market_data import MetricType, Observation, ObservationHead
from ledger.db.models.portfolio import Transaction, TransactionType
from ledger.valuation.replay import PositionState, active_transactions, replay_to_date

ZERO = Decimal("0")


def amount(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def state_pnl(state: PositionState | None, nav: Decimal) -> Decimal:
    if state is None:
        return ZERO
    return state.shares * nav - state.remaining_cost + state.realized_pnl


def calculate_metrics(
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    product_id: uuid.UUID,
    transactions: list[Transaction],
    observations: list[Observation],
    as_of: date,
    method: ValuationMethod,
) -> dict[str, object]:
    # Use the same corrected ledger at both interval endpoints.
    transactions = active_transactions(user_id, transactions, as_of)
    transactions = [
        t for t in transactions if t.account_id == account_id and t.product_id == product_id
    ]
    result: dict[str, object] = {
        "formula_version": "v2",
        "holding_annualized_return": None,
        "holding_pnl": None,
        "latest_income": None,
        "latest_income_per_10k_value": None,
        "official_income_per_10k_shares": None,
        "official_seven_day_annualized": None,
        "quality": "missing",
        "reason": "missing_nav",
        "interval_start": None,
        "interval_end": None,
        "interval_days": None,
        "nav_date": None,
    }
    for metric, field in [
        (MetricType.TEN_THOUSAND_PROFIT, "official_income_per_10k_shares"),
        (MetricType.SEVEN_DAY_ANNUALIZED, "official_seven_day_annualized"),
    ]:
        values = [o for o in observations if o.metric_type == metric and o.valuation_date <= as_of]
        if values:
            latest = max(values, key=lambda o: o.valuation_date)
            result[field] = str(latest.value)
            result[field + "_date"] = latest.valuation_date.isoformat()
    if method != ValuationMethod.NET_VALUE:
        result.update(reason="unsupported_valuation_method", quality="unsupported")
        return result
    navs = sorted(
        (
            o
            for o in observations
            if o.metric_type == MetricType.UNIT_NAV and o.valuation_date <= as_of
        ),
        key=lambda o: o.valuation_date,
    )
    if not navs:
        return result
    latest = navs[-1]
    end = latest.valuation_date
    key = (account_id, product_id)
    state = replay_to_date(user_id, transactions, end).positions.get(key)
    result.update(
        nav_date=end.isoformat(),
        nav_value=str(latest.value),
        quality="complete" if end == as_of else "carried_forward",
        reason=None,
        observation_ids=[str(latest.id)],
    )
    if state:
        holding_pnl = state.shares * latest.value - state.remaining_cost + state.cycle_realized
        result.update(
            holding_pnl=str(holding_pnl),
            capital_days=str(state.capital_days),
            cycle_id=str(state.cycle_id),
            cycle_start=state.cycle_start.isoformat() if state.cycle_start else None,
            cycle_end=state.cycle_end.isoformat() if state.cycle_end else None,
            history_complete=state.history_complete,
            closed_cycles=[
                {
                    "cycle_id": str(cycle_id),
                    **{
                        name: str(value) if value is not None else None
                        for name, value in cycle.items()
                    },
                }
                for cycle_id, cycle in state.closed_cycles.items()
            ],
            market_value=str(state.shares * latest.value),
            unrealized_pnl=str(state.shares * latest.value - state.remaining_cost),
            realized_pnl=str(state.realized_pnl),
            cumulative_pnl=str(state_pnl(state, latest.value)),
        )
        if state.capital_days > 0 and state.history_complete:
            result["holding_annualized_return"] = str(holding_pnl * 365 / state.capital_days)
        else:
            result["annualized_reason"] = (
                "incomplete_history" if not state.history_complete else "zero_capital_days"
            )
    if len(navs) < 2:
        result["latest_reason"] = "missing_previous_nav"
        return result
    previous = navs[-2]
    start = previous.valuation_date
    before = replay_to_date(user_id, transactions, start).positions.get(key)
    interval_txns = [t for t in transactions if start < t.effective_date <= end]
    incomplete = any(t.type == TransactionType.OPENING_BALANCE for t in interval_txns)
    result.update(
        interval_start=start.isoformat(),
        interval_end=end.isoformat(),
        interval_days=(end - start).days,
        observation_ids=[str(previous.id), str(latest.id)],
        beginning_market_value=str(before.shares * previous.value) if before else "0",
        has_cashflows=bool(interval_txns),
    )
    if not incomplete:
        result["latest_income"] = str(
            state_pnl(state, latest.value) - state_pnl(before, previous.value)
        )
    else:
        result["latest_reason"] = "incomplete_history"
    # No verified corporate-action feed yet: distributions require reconciliation.
    if any(
        t.type in {TransactionType.CASH_DIVIDEND, TransactionType.REINVEST_DIVIDEND}
        for t in interval_txns
    ):
        result["tenk_reason"] = "corporate_actions_require_verified_adjustment"
    elif previous.value > 0:
        result["latest_income_per_10k_value"] = str((latest.value / previous.value - 1) * 10000)
    return result


def position_metrics(
    db: Session, user_id: uuid.UUID, account_id: uuid.UUID, product: Product, as_of: date
) -> dict[str, object]:
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.account_id == account_id,
                Transaction.product_id == product.id,
            )
        )
    )
    observations = list(
        db.scalars(
            select(Observation)
            .join(ObservationHead, ObservationHead.observation_id == Observation.id)
            .where(
                ObservationHead.product_id == product.id, ObservationHead.valuation_date <= as_of
            )
        )
    )
    return calculate_metrics(
        user_id, account_id, product.id, transactions, observations, as_of, product.valuation_method
    )
