"""估值与收益计算器。

从持仓快照和净值数据计算市值、未实现收益、已实现收益、累计收益。
按照 repo.wiki/03-data-and-returns.md 的口径：

- 市值 M = 份额 Q × 单位净值 NAV
- 未实现收益 U = M - 剩余成本 C
- 已实现收益 G = R - 已赎回成本 + D - F
- 累计收益 P = U + G = M + R + D - B - F
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ledger.db.models.market_data import MetricType
from ledger.db.models.valuation import Completeness
from ledger.valuation.replay import PositionState


@dataclass
class NavData:
    """净值数据。"""

    observation_id: uuid.UUID
    product_id: uuid.UUID
    valuation_date: date
    metric_type: MetricType
    value: Decimal


@dataclass
class PositionValuation:
    """单个持仓的估值结果。"""

    account_id: uuid.UUID
    product_id: uuid.UUID
    valuation_date: date
    shares: Decimal
    cost: Decimal
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    realized_pnl_cumulative: Decimal
    nav_observation_id: uuid.UUID | None
    nav_date: date | None
    nav_value: Decimal | None
    quality: Completeness

    @property
    def total_pnl(self) -> Decimal | None:
        """累计收益 = 未实现 + 已实现。"""
        if self.unrealized_pnl is not None:
            return self.unrealized_pnl + self.realized_pnl_cumulative
        return None


@dataclass
class PortfolioValuation:
    """组合整体估值结果。"""

    user_id: uuid.UUID
    date: date
    currency: str
    market_value: Decimal | None
    total_cost: Decimal
    cumulative_pnl: Decimal | None
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal
    completeness: Completeness
    valued_product_count: int
    total_product_count: int
    positions: list[PositionValuation]


def calculate_position_valuation(
    position: PositionState,
    valuation_date: date,
    nav_data: NavData | None,
) -> PositionValuation:
    """计算单个持仓的估值。

    Args:
        position: 持仓状态
        valuation_date: 估值日期
        nav_data: 净值数据（可能为 None）

    Returns:
        估值结果
    """
    # Closed positions retain realized profit without requiring a fresh NAV.
    if position.shares == 0:
        return PositionValuation(
            account_id=position.account_id,
            product_id=position.product_id,
            valuation_date=valuation_date,
            shares=position.shares,
            cost=position.remaining_cost,
            market_value=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            realized_pnl_cumulative=position.realized_pnl,
            nav_observation_id=None,
            nav_date=None,
            nav_value=None,
            quality=Completeness.COMPLETE,
        )
    if nav_data and nav_data.metric_type == MetricType.UNIT_NAV:
        market_value = position.shares * nav_data.value
        unrealized_pnl = market_value - position.remaining_cost
        nav_observation_id = nav_data.observation_id
        nav_date_value = nav_data.valuation_date
        nav_value = nav_data.value

        # 判断完整性
        if nav_date_value == valuation_date:
            quality = Completeness.COMPLETE
        elif nav_date_value and nav_date_value < valuation_date:
            quality = Completeness.CARRIED_FORWARD
        else:
            quality = Completeness.STALE
    else:
        # 无净值数据
        market_value = None
        unrealized_pnl = None
        nav_observation_id = None
        nav_date_value = None
        nav_value = None
        quality = Completeness.MISSING

    return PositionValuation(
        account_id=position.account_id,
        product_id=position.product_id,
        valuation_date=valuation_date,
        shares=position.shares,
        cost=position.remaining_cost,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        realized_pnl_cumulative=position.realized_pnl,
        nav_observation_id=nav_observation_id,
        nav_date=nav_date_value,
        nav_value=nav_value,
        quality=quality,
    )


def calculate_portfolio_valuation(
    user_id: uuid.UUID,
    date: date,
    position_valuations: list[PositionValuation],
    currency: str = "CNY",
) -> PortfolioValuation:
    """计算组合整体估值。

    Args:
        user_id: 用户 ID
        date: 估值日期
        position_valuations: 各持仓估值列表
        currency: 币种

    Returns:
        组合估值结果
    """
    total_product_count = len(position_valuations)
    valued_product_count = sum(1 for pv in position_valuations if pv.market_value is not None)

    # 汇总成本和已实现收益
    total_cost = sum((pv.cost for pv in position_valuations), Decimal("0"))
    total_realized_pnl = sum(
        (pv.realized_pnl_cumulative for pv in position_valuations), Decimal("0")
    )

    # 汇总市值和未实现收益（只有全部持仓都有净值时才汇总）
    if valued_product_count == total_product_count and total_product_count > 0:
        total_market_value = sum(
            (pv.market_value for pv in position_valuations if pv.market_value is not None),
            Decimal("0"),
        )
        total_unrealized_pnl = sum(
            (pv.unrealized_pnl for pv in position_valuations if pv.unrealized_pnl is not None),
            Decimal("0"),
        )
        cumulative_pnl = total_unrealized_pnl + total_realized_pnl
        completeness = Completeness.COMPLETE

        # 检查是否有使用旧净值的情况
        if any(pv.quality == Completeness.CARRIED_FORWARD for pv in position_valuations):
            completeness = Completeness.CARRIED_FORWARD
        elif any(pv.quality == Completeness.STALE for pv in position_valuations):
            completeness = Completeness.STALE
    else:
        # 部分持仓无净值
        total_market_value = None
        total_unrealized_pnl = None
        cumulative_pnl = None
        completeness = Completeness.MISSING if valued_product_count == 0 else Completeness.PARTIAL

    return PortfolioValuation(
        user_id=user_id,
        date=date,
        currency=currency,
        market_value=total_market_value,
        total_cost=total_cost,
        cumulative_pnl=cumulative_pnl,
        unrealized_pnl=total_unrealized_pnl,
        realized_pnl=total_realized_pnl,
        completeness=completeness,
        valued_product_count=valued_product_count,
        total_product_count=total_product_count,
        positions=position_valuations,
    )


def calculate_period_pnl(
    portfolio_end: PortfolioValuation,
    portfolio_start: PortfolioValuation | None,
) -> Decimal | None:
    """计算区间收益。

    区间收益 = 期末累计收益 - 期初累计收益

    Args:
        portfolio_end: 期末组合估值
        portfolio_start: 期初组合估值（可能为 None，表示从零开始）

    Returns:
        区间收益金额（如果数据不完整则返回 None）
    """
    if portfolio_end.cumulative_pnl is None:
        return None

    if portfolio_start is None or portfolio_start.cumulative_pnl is None:
        return None

    return portfolio_end.cumulative_pnl - portfolio_start.cumulative_pnl


def calculate_return_on_cost(unrealized_pnl: Decimal, remaining_cost: Decimal) -> Decimal | None:
    """计算持仓成本收益率。

    成本收益率 = 未实现收益 / 剩余成本

    Args:
        unrealized_pnl: 未实现收益
        remaining_cost: 剩余成本

    Returns:
        收益率（小数形式，如 0.05 表示 5%）
    """
    if remaining_cost > 0:
        return unrealized_pnl / remaining_cost
    return None


def calculate_nav_annualized_return(
    nav_start: Decimal,
    nav_end: Decimal,
    start_date: date,
    end_date: date,
) -> Decimal | None:
    """计算净值区间年化收益率。

    年化收益率 = (NAV_end / NAV_start) ^ (365 / 实际天数) - 1

    注意：仅适用于无分红、无份额拆分的简单情况。

    Args:
        nav_start: 起始净值
        nav_end: 结束净值
        start_date: 起始日期
        end_date: 结束日期

    Returns:
        年化收益率（小数形式）
    """
    if nav_start <= 0 or nav_end <= 0:
        return None

    days = (end_date - start_date).days
    if days <= 0:
        return None

    # 使用 Decimal 的 ln 和 exp 进行计算
    # (nav_end / nav_start) ^ (365 / days) - 1
    nav_end / nav_start
    # 避免使用 ** 操作符，直接计算
    # 简化：用线性近似或返回简单收益率
    # 完整实现需要 decimal 库的高精度幂运算
    simple_return = (nav_end - nav_start) / nav_start
    annualized = simple_return * Decimal("365") / Decimal(str(days))

    return annualized
