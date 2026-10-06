"""持仓重放引擎：从交易流水重建持仓快照。

按照移动加权平均成本法，逐笔处理交易事件：
- buy: 增加份额和成本
- redeem: 减少份额，按平均成本结转已实现收益
- cash_dividend: 增加已实现收益
- reinvest_dividend: 增加份额和成本（与分红收入成对）
- fee: 增加已实现费用
- opening_balance: 期初余额
- reversal: 冲正
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ledger.db.models.portfolio import Transaction, TransactionType


@dataclass
class PositionState:
    """单个持仓的状态快照。"""

    account_id: uuid.UUID
    product_id: uuid.UUID
    shares: Decimal = Decimal("0")
    remaining_cost: Decimal = Decimal("0")
    # 已实现收益 = 赎回收入 - 已赎回成本 + 分红 - 独立费用
    realized_pnl: Decimal = Decimal("0")
    # 累计买入总支出（含买入手续费）
    total_bought: Decimal = Decimal("0")
    # 累计赎回净收入（已扣赎回手续费）
    total_redeemed: Decimal = Decimal("0")
    # 累计现金分红
    total_dividends: Decimal = Decimal("0")
    # 累计独立费用
    total_fees: Decimal = Decimal("0")
    last_transaction_date: date | None = None
    cycle_id: uuid.UUID | None = None
    cycle_start: date | None = None
    cycle_end: date | None = None
    cycle_realized: Decimal = Decimal("0")
    capital_days: Decimal = Decimal("0")
    capital_date: date | None = None
    history_complete: bool = True
    closed_cycles: dict[uuid.UUID, dict[str, object]] = field(default_factory=dict)

    def accrue(self, target: date) -> None:
        if self.capital_date is not None:
            days = (target - self.capital_date).days
            if days < 0:
                raise ValueError("transactions_out_of_order")
            self.capital_days += self.remaining_cost * days
        self.capital_date = target

    def apply_transaction(self, txn: Transaction) -> None:
        """应用单笔交易到当前状态。"""
        validate_transaction(txn)
        self.accrue(txn.effective_date)
        if self.shares == 0 and txn.shares_delta > 0:
            if self.cycle_id is not None:
                self.closed_cycles[self.cycle_id] = {
                    "start": self.cycle_start,
                    "end": self.cycle_end,
                    "pnl": self.cycle_realized,
                    "capital_days": self.capital_days,
                }
            self.cycle_id = txn.id
            self.cycle_start = txn.effective_date
            self.cycle_end = None
            self.cycle_realized = Decimal("0")
            self.capital_days = Decimal("0")
            self.history_complete = txn.type != TransactionType.OPENING_BALANCE
        cycle_ref = getattr(txn, "cycle_ref", None)
        if (
            txn.type in {TransactionType.CASH_DIVIDEND, TransactionType.FEE}
            and (self.cycle_end is not None or self.closed_cycles)
            and not cycle_ref
        ):
            raise ValueError("explicit_cycle_reference_required")
        before_realized = self.realized_pnl
        if txn.type == TransactionType.OPENING_BALANCE:
            # 期初余额：直接设置份额和成本
            if self.shares != 0:
                raise ValueError("opening_balance_requires_empty_position")
            self.shares = txn.shares_delta
            self.remaining_cost = txn.cash_amount + txn.fee
            self.total_bought += txn.cash_amount + txn.fee
        elif txn.type == TransactionType.BUY:
            # 买入：增加份额和成本（含手续费）
            self.shares += txn.shares_delta
            cost_with_fee = txn.cash_amount + txn.fee
            self.remaining_cost += cost_with_fee
            self.total_bought += cost_with_fee
        elif txn.type == TransactionType.REDEEM:
            # 赎回：减少份额，按平均成本结转
            if abs(txn.shares_delta) > self.shares:
                raise ValueError("insufficient_shares")
            if self.shares > 0:
                avg_cost_per_share = self.remaining_cost / self.shares
                redeemed_cost = abs(txn.shares_delta) * avg_cost_per_share
                self.remaining_cost -= redeemed_cost
                # 已实现收益 = 赎回到账 - 赎回成本 - 赎回手续费
                realized = txn.cash_amount - redeemed_cost - txn.fee
                self.realized_pnl += realized
            self.shares += txn.shares_delta  # shares_delta 为负
            self.total_redeemed += txn.cash_amount - txn.fee
        elif txn.type == TransactionType.CASH_DIVIDEND:
            # 现金分红：增加已实现收益
            self.realized_pnl += txn.cash_amount - txn.fee
            self.total_dividends += txn.cash_amount
        elif txn.type == TransactionType.REINVEST_DIVIDEND:
            # 红利再投：增加份额和成本
            self.shares += txn.shares_delta
            cost_with_fee = txn.cash_amount + txn.fee
            self.remaining_cost += cost_with_fee
            self.total_bought += cost_with_fee
        elif txn.type == TransactionType.FEE:
            # 独立费用：减少已实现收益
            self.realized_pnl -= txn.cash_amount + txn.fee
            self.total_fees += txn.cash_amount
        elif txn.type == TransactionType.REVERSAL:
            # 冲正：需要找到原交易并反向操作（暂不实现完整逻辑）
            raise ValueError("reversal_requires_replay")

        delta_realized = self.realized_pnl - before_realized
        cycle_ref = getattr(txn, "cycle_ref", None)
        if cycle_ref and cycle_ref != self.cycle_id:
            archived = self.closed_cycles.get(cycle_ref)
            if archived is None:
                raise ValueError("unknown_holding_cycle")
            archived["pnl"] = Decimal(str(archived["pnl"])) + delta_realized
        else:
            self.cycle_realized += delta_realized
        if self.shares == 0 and txn.type == TransactionType.REDEEM:
            self.remaining_cost = Decimal("0")
            self.cycle_end = txn.effective_date

        self.last_transaction_date = txn.effective_date

    @property
    def average_cost_per_share(self) -> Decimal:
        """平均单位成本。"""
        if self.shares > 0:
            return self.remaining_cost / self.shares
        return Decimal("0")


@dataclass
class PortfolioState:
    """用户整体组合的状态。"""

    user_id: uuid.UUID
    positions: dict[tuple[uuid.UUID, uuid.UUID], PositionState] = field(
        default_factory=dict
    )  # (account_id, product_id) -> PositionState

    def get_or_create_position(self, account_id: uuid.UUID, product_id: uuid.UUID) -> PositionState:
        """获取或创建持仓状态。"""
        key = (account_id, product_id)
        if key not in self.positions:
            self.positions[key] = PositionState(account_id=account_id, product_id=product_id)
        return self.positions[key]

    def apply_transaction(self, txn: Transaction) -> None:
        """应用单笔交易。"""
        position = self.get_or_create_position(txn.account_id, txn.product_id)
        position.apply_transaction(txn)


def validate_transaction(txn: Transaction) -> None:
    for value in (txn.shares_delta, txn.cash_amount, txn.fee):
        if not value.is_finite():
            raise ValueError("non_finite_amount")
    for value, scale in ((txn.shares_delta, 12), (txn.cash_amount, 8), (txn.fee, 8)):
        if abs(value) >= Decimal("1e16") or value != value.quantize(Decimal(1).scaleb(-scale)):
            raise ValueError("amount_out_of_range_or_precision")
    if txn.type == TransactionType.REVERSAL and (txn.cash_amount != 0 or txn.fee != 0):
        raise ValueError("reversal_has_cash")
    if txn.cash_amount < 0 or txn.fee < 0:
        raise ValueError("negative_amount")
    if (
        txn.type
        in {TransactionType.BUY, TransactionType.OPENING_BALANCE, TransactionType.REINVEST_DIVIDEND}
        and txn.shares_delta <= 0
    ):
        raise ValueError("positive_shares_required")
    if txn.type == TransactionType.REDEEM and txn.shares_delta >= 0:
        raise ValueError("negative_shares_required")
    if (
        txn.type in {TransactionType.FEE, TransactionType.CASH_DIVIDEND, TransactionType.REVERSAL}
        and txn.shares_delta != 0
    ):
        raise ValueError("cash_event_has_shares")


def active_transactions(
    user_id: uuid.UUID, transactions: list[Transaction], target: date
) -> list[Transaction]:
    eligible = [t for t in transactions if t.effective_date <= target]
    if any(t.user_id != user_id for t in eligible):
        raise ValueError("transaction_owner_mismatch")
    by_id = {t.id: t for t in eligible}
    reversed_ids: set[uuid.UUID] = set()
    for txn in eligible:
        if txn.type != TransactionType.REVERSAL:
            continue
        original = by_id.get(txn.reversal_of) if txn.reversal_of else None
        if (
            original is None
            or original.type == TransactionType.REVERSAL
            or original.account_id != txn.account_id
            or original.product_id != txn.product_id
            or original.id in reversed_ids
        ):
            raise ValueError("invalid_reversal")
        reversed_ids.add(original.id)
    return sorted(
        (t for t in eligible if t.id not in reversed_ids and t.type != TransactionType.REVERSAL),
        key=lambda t: (t.effective_date, str(t.created_at or ""), str(t.id)),
    )


def replay_transactions(user_id: uuid.UUID, transactions: list[Transaction]) -> PortfolioState:
    target = max((t.effective_date for t in transactions), default=date.min)
    return replay_to_date(user_id, transactions, target)


def replay_to_date(
    user_id: uuid.UUID, transactions: list[Transaction], target_date: date
) -> PortfolioState:
    portfolio = PortfolioState(user_id=user_id)
    for txn in active_transactions(user_id, transactions, target_date):
        portfolio.apply_transaction(txn)
    for position in portfolio.positions.values():
        position.accrue(target_date)
    return portfolio


def replay_daily_snapshots(
    user_id: uuid.UUID, transactions: list[Transaction], from_date: date, to_date: date
) -> dict[date, PortfolioState]:
    from datetime import timedelta

    snapshots: dict[date, PortfolioState] = {}
    # Reversals correct the referenced event from its original effective date.
    active = active_transactions(user_id, transactions, to_date)
    portfolio = PortfolioState(user_id=user_id)
    index = 0
    current = from_date
    while current <= to_date:
        while index < len(active) and active[index].effective_date <= current:
            portfolio.apply_transaction(active[index])
            index += 1
        for position in portfolio.positions.values():
            position.accrue(current)
        snapshots[current] = deepcopy(portfolio)
        current += timedelta(days=1)
    return snapshots
