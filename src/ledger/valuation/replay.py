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
from dataclasses import dataclass, field
from datetime import date as Date
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
    last_transaction_date: Date | None = None

    def apply_transaction(self, txn: Transaction) -> None:
        """应用单笔交易到当前状态。"""
        if txn.type == TransactionType.OPENING_BALANCE:
            # 期初余额：直接设置份额和成本
            self.shares = txn.shares_delta
            self.remaining_cost = txn.cash_amount
            self.total_bought = txn.cash_amount
        elif txn.type == TransactionType.BUY:
            # 买入：增加份额和成本（含手续费）
            self.shares += txn.shares_delta
            cost_with_fee = txn.cash_amount + txn.fee
            self.remaining_cost += cost_with_fee
            self.total_bought += cost_with_fee
        elif txn.type == TransactionType.REDEEM:
            # 赎回：减少份额，按平均成本结转
            if self.shares > 0:
                avg_cost_per_share = self.remaining_cost / self.shares
                redeemed_cost = abs(txn.shares_delta) * avg_cost_per_share
                self.remaining_cost -= redeemed_cost
                # 已实现收益 = 赎回到账 - 赎回成本 - 赎回手续费
                realized = txn.cash_amount - redeemed_cost - txn.fee
                self.realized_pnl += realized
            self.shares += txn.shares_delta  # shares_delta 为负
            self.total_redeemed += txn.cash_amount
        elif txn.type == TransactionType.CASH_DIVIDEND:
            # 现金分红：增加已实现收益
            self.realized_pnl += txn.cash_amount
            self.total_dividends += txn.cash_amount
        elif txn.type == TransactionType.REINVEST_DIVIDEND:
            # 红利再投：增加份额和成本
            self.shares += txn.shares_delta
            cost_with_fee = txn.cash_amount + txn.fee
            self.remaining_cost += cost_with_fee
            self.total_bought += cost_with_fee
        elif txn.type == TransactionType.FEE:
            # 独立费用：减少已实现收益
            self.realized_pnl -= txn.cash_amount
            self.total_fees += txn.cash_amount
        elif txn.type == TransactionType.REVERSAL:
            # 冲正：需要找到原交易并反向操作（暂不实现完整逻辑）
            pass

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


def replay_transactions(
    user_id: uuid.UUID,
    transactions: list[Transaction],
) -> PortfolioState:
    """从交易流水重建持仓状态。

    Args:
        user_id: 用户 ID
        transactions: 按 effective_Date, created_at 排序的交易列表

    Returns:
        重放后的组合状态
    """
    portfolio = PortfolioState(user_id=user_id)
    for txn in transactions:
        portfolio.apply_transaction(txn)
    return portfolio


def replay_to_date(
    user_id: uuid.UUID,
    transactions: list[Transaction],
    target_date: Date,
) -> PortfolioState:
    """重放到指定日期的持仓状态。

    Args:
        user_id: 用户 ID
        transactions: 全部交易流水（按日期排序）
        target_date: 目标日期（包含当日确认的交易）

    Returns:
        目标日期收盘时的组合状态
    """
    portfolio = PortfolioState(user_id=user_id)
    for txn in transactions:
        if txn.effective_date <= target_date:
            portfolio.apply_transaction(txn)
        else:
            break
    return portfolio


def replay_daily_snapshots(
    user_id: uuid.UUID,
    transactions: list[Transaction],
    from_date: Date,
    to_date: Date,
) -> dict[Date, PortfolioState]:
    """生成日期区间内每日的持仓快照。

    Args:
        user_id: 用户 ID
        transactions: 全部交易流水（按日期排序）
        from_date: 起始日期
        to_date: 结束日期

    Returns:
        日期 -> 持仓状态的字典
    """
    snapshots: dict[Date, PortfolioState] = {}
    portfolio = PortfolioState(user_id=user_id)

    # 重放到起始日期前一天
    for txn in transactions:
        if txn.effective_date < from_date:
            portfolio.apply_transaction(txn)
        else:
            break

    # 逐日生成快照
    current_date = from_date
    txn_index = 0
    # 跳过已处理的交易
    while txn_index < len(transactions) and transactions[txn_index].effective_date < from_date:
        txn_index += 1

    while current_date <= to_date:
        # 应用当日的所有交易
        while (
            txn_index < len(transactions) and transactions[txn_index].effective_date == current_date
        ):
            portfolio.apply_transaction(transactions[txn_index])
            txn_index += 1

        # 深拷贝当前状态作为快照
        snapshot = PortfolioState(
            user_id=portfolio.user_id,
            positions={
                key: PositionState(
                    account_id=pos.account_id,
                    product_id=pos.product_id,
                    shares=pos.shares,
                    remaining_cost=pos.remaining_cost,
                    realized_pnl=pos.realized_pnl,
                    total_bought=pos.total_bought,
                    total_redeemed=pos.total_redeemed,
                    total_dividends=pos.total_dividends,
                    total_fees=pos.total_fees,
                    last_transaction_date=pos.last_transaction_date,
                )
                for key, pos in portfolio.positions.items()
            },
        )
        snapshots[current_date] = snapshot

        # 下一天
        from datetime import timedelta

        current_date += timedelta(days=1)

    return snapshots
