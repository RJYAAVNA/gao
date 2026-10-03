"""组合汇总服务层。

提供用户资产概览、持仓汇总等查询。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ledger.db.models.catalog import Product
from ledger.db.models.portfolio import Position
from ledger.db.models.valuation import PortfolioSnapshot, PositionSnapshot, ValuationRun

if TYPE_CHECKING:
    pass


@dataclass
class PortfolioSummary:
    """组合汇总数据。"""

    total_market_value: Decimal
    total_cost: Decimal
    total_pnl: Decimal
    total_return: Decimal
    position_count: int
    annualized_return: Decimal
    valuation_date: date


@dataclass
class PositionSummary:
    """持仓汇总数据。"""

    id: uuid.UUID
    account_id: uuid.UUID
    product_id: uuid.UUID
    product_code: str
    product_name: str
    shares: Decimal
    cost: Decimal
    market_value: Decimal
    pnl: Decimal
    return_rate: Decimal


def get_portfolio_summary(
    db: Session,
    user_id: uuid.UUID,
) -> PortfolioSummary | None:
    """获取用户的组合汇总数据。

    从最新的估值快照中获取汇总信息。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        组合汇总数据，如果没有估值数据则返回 None
    """
    # 查询用户最新的估值任务
    run_stmt = (
        select(ValuationRun)
        .where(
            and_(
                ValuationRun.user_id == user_id,
                ValuationRun.is_current.is_(True),
            )
        )
        .order_by(ValuationRun.created_at.desc())
        .limit(1)
    )
    run = db.scalar(run_stmt)

    if not run:
        # 如果没有估值数据，返回空汇总
        return None

    # 查询最新的组合快照
    snapshot_stmt = (
        select(PortfolioSnapshot)
        .where(
            and_(
                PortfolioSnapshot.run_id == run.id,
                PortfolioSnapshot.user_id == user_id,
            )
        )
        .order_by(PortfolioSnapshot.date.desc())
        .limit(1)
    )
    snapshot = db.scalar(snapshot_stmt)

    if not snapshot:
        return None

    # 计算年化收益率（简化版本，假设持有期为估值日期范围）
    days = (snapshot.date - run.from_date).days
    if days > 0 and snapshot.total_cost > 0 and snapshot.cumulative_pnl:
        annualized_return = (
            snapshot.cumulative_pnl / snapshot.total_cost * Decimal(365) / Decimal(days)
        )
    else:
        annualized_return = Decimal(0)

    # 计算总收益率
    if snapshot.total_cost > 0 and snapshot.cumulative_pnl:
        total_return = snapshot.cumulative_pnl / snapshot.total_cost
    else:
        total_return = Decimal(0)

    return PortfolioSummary(
        total_market_value=snapshot.market_value or Decimal(0),
        total_cost=snapshot.total_cost,
        total_pnl=snapshot.cumulative_pnl or Decimal(0),
        total_return=total_return,
        position_count=snapshot.valued_product_count,
        annualized_return=annualized_return,
        valuation_date=snapshot.date,
    )


def get_top_positions(
    db: Session,
    user_id: uuid.UUID,
    limit: int = 10,
) -> list[PositionSummary]:
    """获取用户的主要持仓列表。

    从最新的估值快照中获取持仓数据，按市值降序排列。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        limit: 返回的持仓数量

    Returns:
        持仓汇总列表
    """
    # 查询用户最新的估值任务
    run_stmt = (
        select(ValuationRun)
        .where(
            and_(
                ValuationRun.user_id == user_id,
                ValuationRun.is_current.is_(True),
            )
        )
        .order_by(ValuationRun.created_at.desc())
        .limit(1)
    )
    run = db.scalar(run_stmt)

    if not run:
        return []

    # 查询最新估值日期
    date_stmt = (
        select(func.max(PortfolioSnapshot.date))
        .where(
            and_(
                PortfolioSnapshot.run_id == run.id,
                PortfolioSnapshot.user_id == user_id,
            )
        )
    )
    latest_date = db.scalar(date_stmt)

    if not latest_date:
        return []

    # 查询该日期的持仓快照，并关联产品信息
    snapshot_stmt = (
        select(PositionSnapshot, Product, Position)
        .join(Product, PositionSnapshot.product_id == Product.id)
        .join(
            Position,
            and_(
                Position.account_id == PositionSnapshot.account_id,
                Position.product_id == PositionSnapshot.product_id,
            ),
        )
        .where(
            and_(
                PositionSnapshot.run_id == run.id,
                PositionSnapshot.user_id == user_id,
                PositionSnapshot.date == latest_date,
                PositionSnapshot.shares > 0,
            )
        )
        .order_by(PositionSnapshot.market_value.desc())
        .limit(limit)
    )
    results = db.execute(snapshot_stmt).all()

    summaries = []
    for snapshot, product, position in results:
        # 计算收益率
        if snapshot.cost > 0 and snapshot.unrealized_pnl:
            return_rate = snapshot.unrealized_pnl / snapshot.cost
        else:
            return_rate = Decimal(0)

        summaries.append(
            PositionSummary(
                id=position.id,
                account_id=snapshot.account_id,
                product_id=snapshot.product_id,
                product_code=product.issuer_code,
                product_name=product.name,
                shares=snapshot.shares,
                cost=snapshot.cost,
                market_value=snapshot.market_value or Decimal(0),
                pnl=snapshot.unrealized_pnl or Decimal(0),
                return_rate=return_rate,
            )
        )

    return summaries


def get_simple_portfolio_summary(
    db: Session,
    user_id: uuid.UUID,
) -> PortfolioSummary:
    """获取简化的组合汇总数据。

    如果没有估值数据，则基于当前持仓计算简单汇总。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        组合汇总数据
    """
    # 先尝试获取估值快照数据
    summary = get_portfolio_summary(db, user_id)
    if summary:
        return summary

    # 如果没有估值数据，返回基于持仓的简单汇总
    position_stmt = (
        select(Position)
        .where(
            and_(
                Position.user_id == user_id,
                Position.shares > 0,
            )
        )
    )
    positions = db.scalars(position_stmt).all()

    total_cost = sum(pos.remaining_cost for pos in positions)
    position_count = len(positions)

    return PortfolioSummary(
        total_market_value=Decimal(0),  # 需要估值才能计算
        total_cost=total_cost,
        total_pnl=Decimal(0),
        total_return=Decimal(0),
        position_count=position_count,
        annualized_return=Decimal(0),
        valuation_date=date.today(),
    )
