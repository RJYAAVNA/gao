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
    reversal_of: uuid.UUID | None = None,
    cycle_ref: uuid.UUID | None = None,
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
    from ledger.db.models.catalog import Product
    from ledger.db.models.identity import User
    from ledger.db.models.portfolio import BankAccount
    from ledger.valuation.replay import validate_transaction

    db.execute(select(User.id).where(User.id == user_id).with_for_update())
    if idempotency_key and db.scalar(
        select(Transaction.id).where(
            Transaction.user_id == user_id, Transaction.idempotency_key == idempotency_key
        )
    ):
        raise DuplicateTransactionError("idempotency_key_exists")
    account = db.scalar(
        select(BankAccount)
        .where(BankAccount.id == account_id, BankAccount.user_id == user_id)
        .with_for_update()
    )
    if account is None:
        raise TransactionNotFoundError("account_not_found")
    product = db.get(Product, product_id)
    if product is None:
        raise TransactionNotFoundError("product_not_found")
    if product.currency != account.currency:
        raise ValueError("account_product_currency_mismatch")
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
        reversal_of=reversal_of,
        cycle_ref=cycle_ref,
    )
    validate_transaction(txn)
    if txn_type == TransactionType.REINVEST_DIVIDEND:
        # The dividend and purchase are one atomic business event, not two HTTP requests.
        income = Transaction(
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            type=TransactionType.CASH_DIVIDEND,
            effective_date=effective_date,
            shares_delta=Decimal(0),
            cash_amount=cash_amount,
            fee=Decimal(0),
            cycle_ref=cycle_ref,
        )
        db.add(income)
        db.flush()
        txn.linked_transaction_id = income.id
    db.add(txn)

    try:
        db.flush()
    except IntegrityError as e:
        if "uq_transactions_user_idem" in str(e):
            raise DuplicateTransactionError(f"幂等键 '{idempotency_key}' 已存在") from None
        raise

    if txn_type == TransactionType.REINVEST_DIVIDEND:
        income.linked_transaction_id = txn.id
        db.flush()
    if txn_type == TransactionType.REVERSAL and reversal_of:
        original = get_transaction(db, user_id, reversal_of)
        if original.linked_transaction_id:
            linked = get_transaction(db, user_id, original.linked_transaction_id)
            db.add(
                Transaction(
                    user_id=user_id,
                    account_id=account_id,
                    product_id=product_id,
                    type=TransactionType.REVERSAL,
                    effective_date=effective_date,
                    shares_delta=Decimal(0),
                    cash_amount=Decimal(0),
                    fee=Decimal(0),
                    reversal_of=linked.id,
                )
            )
            db.flush()
    # 更新持仓投影
    rebuild_positions_for_account(db, user_id, account_id)

    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import func

    from ledger.valuation.service import trigger_valuation

    start = db.scalar(
        select(func.min(Transaction.effective_date)).where(Transaction.user_id == user_id)
    )
    if start:
        trigger_valuation(db, user_id, start, datetime.now(ZoneInfo("Asia/Shanghai")).date())
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

    from ledger.valuation.replay import PositionState

    state = PositionState(
        account_id=account_id,
        product_id=product_id,
        shares=pos.shares,
        remaining_cost=pos.remaining_cost,
        realized_pnl=pos.realized_pnl,
    )
    state.apply_transaction(txn)
    pos.shares, pos.remaining_cost, pos.realized_pnl = (
        state.shares,
        state.remaining_cost,
        state.realized_pnl,
    )
    pos.last_transaction_date = txn.effective_date
    pos.ledger_version += 1
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
    from ledger.valuation.replay import replay_transactions

    transactions = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.user_id == user_id, Transaction.account_id == account_id)
            .order_by(Transaction.effective_date, Transaction.created_at, Transaction.id)
        )
    )
    state = replay_transactions(user_id, transactions)
    existing = {
        p.product_id: p
        for p in db.scalars(
            select(Position)
            .where(Position.user_id == user_id, Position.account_id == account_id)
            .with_for_update()
        )
    }
    for (_, product_id), item in state.positions.items():
        pos = existing.pop(product_id, None)
        if pos is None:
            pos = Position(
                user_id=user_id, account_id=account_id, product_id=product_id, ledger_version=0
            )
            db.add(pos)
        pos.shares, pos.remaining_cost, pos.realized_pnl = (
            item.shares,
            item.remaining_cost,
            item.realized_pnl,
        )
        pos.last_transaction_date = item.last_transaction_date
        pos.ledger_version += 1
    for pos in existing.values():
        pos.shares = pos.remaining_cost = pos.realized_pnl = Decimal("0")
        pos.ledger_version += 1
    db.flush()
