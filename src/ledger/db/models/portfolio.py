"""用户私有数据：银行账户、交易流水、持仓投影、导入批次。

用户隔离在数据库层面强制（对应 repo.wiki/03-data-and-returns.md）：
- bank_accounts 上有 UNIQUE(user_id, id)，让 transactions 能用复合外键
  (user_id, account_id) 引用，从而无法把自己的流水绑到别人的账户。
- 服务层另有 user_id 过滤；两层防护都保留。
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ledger.db.base import Base, TimestampMixin, UUIDPrimaryKey, enum_column


class BankAccount(Base, UUIDPrimaryKey, TimestampMixin):
    """用户的银行账户。不保存完整卡号。"""

    __tablename__ = "bank_accounts"
    __table_args__ = (
        # 供 transactions 的复合外键引用，是用户隔离的数据库级基础
        UniqueConstraint("user_id", "id", name="uq_bank_accounts_user_id_id"),
        UniqueConstraint("user_id", "alias", name="uq_bank_accounts_user_alias"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    # 仅存尾号等脱敏信息，如 "****1234"
    masked_account: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)


class TransactionType(str, enum.Enum):
    """交易事件类型。

    cash_amount 一律为非负业务金额，方向由类型解释；
    份额增减记在 shares_delta，手续费单独记录，避免重复扣减。
    """

    OPENING_BALANCE = "opening_balance"  # 期初余额（迁移或首次录入）
    BUY = "buy"  # 买入/申购
    REDEEM = "redeem"  # 赎回
    CASH_DIVIDEND = "cash_dividend"  # 现金分红
    REINVEST_DIVIDEND = "reinvest_dividend"  # 红利再投（与分红收入成对登记）
    FEE = "fee"  # 独立费用
    REVERSAL = "reversal"  # 冲正


class Transaction(Base, UUIDPrimaryKey, TimestampMixin):
    """交易流水。已确认流水不原地修改，用冲正 + 补录更正。"""

    __tablename__ = "transactions"
    __table_args__ = (
        # 复合外键：账户必须属于同一个 user_id
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["bank_accounts.user_id", "bank_accounts.id"],
            name="fk_transactions_user_account",
            ondelete="CASCADE",
        ),
        # 用户范围内的幂等键，供账单导入去重
        UniqueConstraint("user_id", "idempotency_key", name="uq_transactions_user_idem"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )

    type: Mapped[TransactionType] = mapped_column(
        enum_column(TransactionType, "transaction_type"), nullable=False
    )
    # 确认生效日（份额实际变动日），不是申请日
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 份额增减：买入为正，赎回为负，纯现金事件为 0
    shares_delta: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0, nullable=False)
    # 非负业务金额
    cash_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0, nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0, nullable=False)

    # 外部参考号（银行流水号），用于对账
    external_ref: Mapped[str | None] = mapped_column(String(128))
    # 导入去重用：文件 hash + 行号 或 external_ref 派生
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    # 冲正指向被冲正的原流水
    reversal_of: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("transactions.id", ondelete="RESTRICT")
    )
    # 红利再投的两条关联事件互相引用
    linked_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL")
    )
    cycle_ref: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(String(512))


class Position(Base, UUIDPrimaryKey, TimestampMixin):
    """当前持仓。

    这是可从 transactions 完全重建的投影，不是真相来源。
    remaining_cost 用移动加权平均法维护。
    """

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "product_id", name="uq_positions_identity"),
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["bank_accounts.user_id", "bank_accounts.id"],
            name="fk_positions_user_account",
            ondelete="CASCADE",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )

    shares: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0, nullable=False)
    remaining_cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0, nullable=False)
    # 累计已实现收益，全部赎回后仍保留
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0, nullable=False)
    # 乐观锁 / 重建版本号
    ledger_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_transaction_date: Mapped[date | None] = mapped_column(Date)


class ImportStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PREVIEW_READY = "preview_ready"  # 已解析，待用户确认映射
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"


class ImportBatch(Base, UUIDPrimaryKey, TimestampMixin):
    """账单/台账导入批次。预览 → 确认两步，避免误导入。"""

    __tablename__ = "import_batches"
    __table_args__ = (
        # 同一用户重复上传同一文件按 hash 去重
        UniqueConstraint("user_id", "file_sha256", name="uq_import_batches_user_file"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("raw_artifacts.id", ondelete="SET NULL")
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[ImportStatus] = mapped_column(
        enum_column(ImportStatus, "import_status"),
        default=ImportStatus.UPLOADED,
        nullable=False,
    )
    # 列映射方案版本，解析规则变化时可区分
    mapping_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(String(1024))
