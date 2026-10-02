"""交易流水服务层。

职责：
- 用户隔离的交易记录查询与创建
- 幂等键去重
- 持仓投影更新（移动加权平均成本法）
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ledger.db.models.portfolio import Position, Transaction, TransactionType

if TYPE_CHECKING:
    pass


class TransactionServiceError(Exception):
    """交易服务异常基类。"""

    pass


class TransactionNotFoundError(TransactionServiceError):
    """交易不存在或无权访问。"""

    pass


class DuplicateTransactionError(TransactionServiceError):
    """幂等键重复，交易已存在。"""

    pass


def list_transactions(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 100,
) -> list[Transaction]:
    """列出交易流水。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 可选，筛选账户
        product_id: 可选，筛选产品
        start_date: 可选，起始日期（含）
        end_date: 可选，结束日期（含）
        limit: 返回条数上限

    Returns:
        交易流水列表，按生效日期倒序
    """
    stmt = select(Transaction).where(Transaction.user_id == user_id)

    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if product_id is not None:
        stmt = stmt.where(Transaction.product_id == product_id)
    if start_date is not None:
        stmt = stmt.where(Transaction.effective_date >= start_date)
    if end_date is not None:
        stmt = stmt.where(Transaction.effective_date <= end_date)

    stmt = stmt.order_by(Transaction.effective_date.desc(), Transaction.created_at.desc()).limit(
        limit
    )
    return list(db.scalars(stmt))


def get_transaction(db: Session, user_id: uuid.UUID, transaction_id: uuid.UUID) -> Transaction:
    """获取单条交易。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        transaction_id: 交易 ID

    Returns:
        交易对象

    Raises:
        TransactionNotFoundError: 交易不存在或无权访问
    """
    stmt = select(Transaction).where(
        Transaction.id == transaction_id,
        Transaction.user_id == user_id,
    )
    txn = db.scalar(stmt)
    if txn is None:
        raise TransactionNotFoundError(f"交易 {transaction_id} 不存在或无权访问")
    return txn


def create_transaction(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    product_id: uuid.UUID,
    txn_type: TransactionType,
    effective_date: date,
    shares_delta: Decimal,
    cash_amount: Decimal,
    fee: Decimal = Decimal(0),
    external_ref: str | None = None,
    idempotency_key: str | None = None,
    import_batch_id: uuid.UUID | None = None,
    note: str | None = None,
) -> Transaction:
    """创建交易流水并更新持仓。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 账户 ID
        product_id: 产品 ID
        txn_type: 交易类型
        effective_date: 生效日期
        shares_delta: 份额变动（买入为正，赎回为负）
        cash_amount: 现金金额（非负）
        fee: 手续费
        external_ref: 外部流水号
        idempotency_key: 幂等键
        import_batch_id: 导入批次 ID
        note: 备注

    Returns:
        创建的交易对象

    Raises:
        DuplicateTransactionError: 幂等键重复
    """
    txn = Transaction(
        user_id=user_id,
        account_id=account_id,
        product_id=product_id,
        type=txn_type,
        effective_date=effective_date,
        shares_delta=shares_delta,
        cash_amount=cash_amount,
        fee=fee,
        external_ref=external_ref,
        idempotency_key=idempotency_key,
        import_batch_id=import_batch_id,
        note=note,
    )
    db.add(txn)

    try:
        db.flush()
    except IntegrityError as e:
        if "uq_transactions_user_idem" in str(e):
            raise DuplicateTransactionError(f"幂等键 '{idempotency_key}' 已存在") from None
        raise

    # 更新持仓投影
    _update_position(db, user_id, account_id, product_id, txn)

    return txn


def _update_position(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    product_id: uuid.UUID,
    txn: Transaction,
) -> None:
    """根据交易更新持仓投影。

    使用移动加权平均成本法：
    - 买入：增加份额，按比例分摊成本
    - 赎回：减少份额，确认实现收益
    """
    stmt = select(Position).where(
        Position.user_id == user_id,
        Position.account_id == account_id,
        Position.product_id == product_id,
    )
    pos = db.scalar(stmt)

    if pos is None:
        # 首次建仓
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

    # 份额变动
    pos.shares += txn.shares_delta
    pos.last_transaction_date = txn.effective_date
    pos.ledger_version += 1

    # 成本与收益核算
    if txn.type in (
        TransactionType.BUY,
        TransactionType.OPENING_BALANCE,
        TransactionType.REINVEST_DIVIDEND,
    ):
        # 买入/期初/再投：成本累加
        pos.remaining_cost += txn.cash_amount + txn.fee
    elif txn.type == TransactionType.REDEEM:
        # 赎回：按份额比例减少成本，差额记为已实现收益
        if pos.shares > 0 and txn.shares_delta < 0:
            # 单位成本
            unit_cost = pos.remaining_cost / pos.shares if pos.shares != 0 else Decimal(0)
            # 本次赎回对应成本
            cost_reduction = abs(txn.shares_delta) * unit_cost
            # 已实现收益 = 赎回金额 - 成本 - 手续费
            pos.realized_pnl += txn.cash_amount - cost_reduction - txn.fee
            pos.remaining_cost -= cost_reduction
    elif txn.type == TransactionType.CASH_DIVIDEND:
        # 现金分红：直接计入已实现收益
        pos.realized_pnl += txn.cash_amount - txn.fee
    elif txn.type == TransactionType.FEE:
        # 独立费用：从剩余成本扣除
        pos.remaining_cost -= txn.fee

    db.flush()


def rebuild_positions_for_account(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    """从交易流水重建账户的所有持仓。

    清空现有持仓，按时间顺序重放所有交易。用于修复数据或迁移后重算。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        account_id: 账户 ID
    """
    # 清空现有持仓
    stmt = select(Position).where(
        Position.user_id == user_id,
        Position.account_id == account_id,
    )
    positions = db.scalars(stmt).all()
    for pos in positions:
        db.delete(pos)
    db.flush()

    # 按时间顺序重放交易
    txn_stmt = (
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.account_id == account_id,
        )
        .order_by(Transaction.effective_date, Transaction.created_at)
    )
    transactions = db.scalars(txn_stmt).all()

    for txn in transactions:
        _update_position(db, user_id, account_id, txn.product_id, txn)

    db.flush()
