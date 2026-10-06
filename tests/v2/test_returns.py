"""Numeric acceptance examples and invariants independent of UI formatting."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from ledger.db.models import MetricType as M
from ledger.db.models import Observation, Transaction, ValuationMethod
from ledger.db.models import TransactionType as T
from ledger.valuation.calculator import calculate_position_valuation
from ledger.valuation.metrics import calculate_metrics
from ledger.valuation.replay import replay_to_date

USER, ACCOUNT, PRODUCT, SOURCE = [uuid.uuid4() for _ in range(4)]


def txn(day, kind=T.BUY, shares="10000", cash="10000", fee="0", **extra):
    return Transaction(
        id=uuid.uuid4(),
        user_id=USER,
        account_id=ACCOUNT,
        product_id=PRODUCT,
        effective_date=date.fromisoformat(day),
        type=kind,
        shares_delta=Decimal(shares),
        cash_amount=Decimal(cash),
        fee=Decimal(fee),
        created_at=datetime.now(UTC),
        **extra,
    )


def nav(day, value, metric=M.UNIT_NAV):
    return Observation(
        id=uuid.uuid4(),
        product_id=PRODUCT,
        source_id=SOURCE,
        valuation_date=date.fromisoformat(day),
        metric_type=metric,
        value=Decimal(value),
    )


def metrics(transactions, observations, day="2026-01-31", method=ValuationMethod.NET_VALUE):
    return calculate_metrics(
        USER, ACCOUNT, PRODUCT, transactions, observations, date.fromisoformat(day), method
    )


def test_capital_weighted_annualization_and_stale_freeze():
    trades = [txn("2026-01-01")]
    observations = [nav("2026-01-01", "1"), nav("2026-01-31", "1.003")]
    result = metrics(trades, observations)
    assert Decimal(result["holding_pnl"]) == Decimal("30")
    assert Decimal(result["holding_annualized_return"]) == Decimal("0.0365")
    assert Decimal(result["capital_days"]) == Decimal("300000")
    stale = metrics(trades, observations, "2026-02-10")
    assert stale["holding_annualized_return"] == result["holding_annualized_return"]
    assert stale["quality"] == "carried_forward"


def test_latest_tenk_and_true_zero():
    result = metrics(
        [txn("2026-01-01", shares="100000", cash="100000")],
        [nav("2026-01-01", "1"), nav("2026-01-02", "1.00004")],
        "2026-01-02",
    )
    assert Decimal(result["latest_income"]) == 4
    assert Decimal(result["latest_income_per_10k_value"]) == Decimal(".40")
    zero = metrics(
        [txn("2026-01-01")], [nav("2026-01-01", "1"), nav("2026-01-02", "1")], "2026-01-02"
    )
    assert Decimal(zero["latest_income"]) == 0
    missing = metrics([txn("2026-01-01")], [])
    assert missing["latest_income"] is None


def test_partial_and_full_redemption_keep_realized_profit():
    trades = [txn("2026-01-01", shares="100", cash="100"), txn("2026-01-02", T.REDEEM, "-50", "55")]
    state = replay_to_date(USER, trades, date(2026, 1, 2)).positions[(ACCOUNT, PRODUCT)]
    assert (state.shares, state.remaining_cost, state.realized_pnl) == (
        Decimal("50"),
        Decimal("50"),
        Decimal("5"),
    )
    trades.append(txn("2026-01-03", T.REDEEM, "-50", "55"))
    state = replay_to_date(USER, trades, date(2026, 1, 3)).positions[(ACCOUNT, PRODUCT)]
    value = calculate_position_valuation(state, date(2026, 1, 3), None)
    assert value.market_value == 0 and value.total_pnl == 10


def test_cashflows_are_not_current_shares_times_delta():
    trades = [
        txn("2026-01-01", shares="100", cash="100"),
        txn("2026-01-02", shares="100", cash="110"),
    ]
    result = metrics(trades, [nav("2026-01-01", "1"), nav("2026-01-02", "1.1")], "2026-01-02")
    assert Decimal(result["latest_income"]) == 10  # 200 * .1 would incorrectly give 20.


def test_reopened_cycle_and_late_dividend_reference():
    first = txn("2026-01-01", shares="100", cash="100")
    trades = [
        first,
        txn("2026-01-02", T.REDEEM, "-100", "110"),
        txn("2026-01-03", shares="100", cash="100"),
    ]
    trades.append(txn("2026-01-04", T.CASH_DIVIDEND, "0", "2", cycle_ref=first.id))
    state = replay_to_date(USER, trades, date(2026, 1, 4)).positions[(ACCOUNT, PRODUCT)]
    assert state.realized_pnl == 12 and state.cycle_realized == 0
    assert state.closed_cycles[first.id]["pnl"] == 12
    assert state.capital_days == 100


def test_reversal_corrects_cost_and_cannot_cross_user():
    original = txn("2026-01-01")
    cancel = txn("2026-01-02", T.REVERSAL, "0", "0", reversal_of=original.id)
    assert replay_to_date(USER, [original, cancel], date(2026, 1, 3)).positions == {}
    original.user_id = uuid.uuid4()
    with pytest.raises(ValueError, match="owner"):
        replay_to_date(USER, [original], date(2026, 1, 3))


@pytest.mark.parametrize("cash,shares", [("-1", "1"), ("NaN", "1"), ("Infinity", "1"), ("1", "0")])
def test_invalid_amounts(cash, shares):
    with pytest.raises(ValueError):
        replay_to_date(USER, [txn("2026-01-01", cash=cash, shares=shares)], date(2026, 1, 2))


def test_cash_management_official_zero_without_fake_valuation():
    result = metrics(
        [], [nav("2026-01-02", "0", M.TEN_THOUSAND_PROFIT)], method=ValuationMethod.CASH_MANAGEMENT
    )
    assert result["official_income_per_10k_shares"] == "0"
    assert result["holding_annualized_return"] is None
    assert result["reason"] == "unsupported_valuation_method"


def test_multiday_interval_and_incomplete_opening():
    result = metrics(
        [txn("2026-01-01")], [nav("2026-01-02", "1"), nav("2026-01-05", "1.0003")], "2026-01-05"
    )
    assert result["interval_days"] == 3 and Decimal(result["latest_income_per_10k_value"]) == 3
    opening = metrics(
        [txn("2026-01-01", T.OPENING_BALANCE)], [nav("2026-01-01", "1"), nav("2026-01-31", "1.003")]
    )
    assert opening["holding_annualized_return"] is None
