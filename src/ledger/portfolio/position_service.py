"""持仓查询服务层。

持仓是交易流水的投影，不是真相来源。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.db.models.portfolio import Position

if TYPE_CHECKING:
    pass


class PositionServiceError(Exception):
    """持仓服务异常基类。"""

    pass


class PositionNotFoundError(PositionServiceError):
    """持仓不存在或无权访问。"""

    pass


def list_positions(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    include_zero_shares: bool = False,
) -> list[Position]:
    """列出用户的持仓。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 可选，筛选账户
        include_zero_shares: 是否包含已清仓（份额为 0）的持仓

    Returns:
        持仓列表
    """
    stmt = select(Position).where(Position.user_id == user_id)

    if account_id is not None:
        stmt = stmt.where(Position.account_id == account_id)

    if not include_zero_shares:
        stmt = stmt.where(Position.shares > 0)

    stmt = stmt.order_by(Position.account_id, Position.product_id)
    return list(db.scalars(stmt))


def get_position(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Position:
    """获取单个持仓。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 账户 ID
        product_id: 产品 ID

    Returns:
        持仓对象

    Raises:
        PositionNotFoundError: 持仓不存在或无权访问
    """
    stmt = select(Position).where(
        Position.user_id == user_id,
        Position.account_id == account_id,
        Position.product_id == product_id,
    )
    pos = db.scalar(stmt)
    if pos is None:
        raise PositionNotFoundError(f"持仓 ({account_id}, {product_id}) 不存在或无权访问")
    return pos


def get_or_create_position(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Position:
    """获取或创建持仓记录。

    用于确保持仓记录存在，便于后续更新。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 账户 ID
        product_id: 产品 ID

    Returns:
        持仓对象
    """
    try:
        return get_position(db, user_id, account_id, product_id)
    except PositionNotFoundError:
        from decimal import Decimal

        pos = Position(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            shares=Decimal(0),
            remaining_cost=Decimal(0),
            realized_pnl=Decimal(0),
            ledger_version=1,
        )
        db.add(pos)
        db.flush()
        return pos
