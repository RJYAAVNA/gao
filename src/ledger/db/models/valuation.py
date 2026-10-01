"""估值快照与收益报表。

版本化计算（对应 repo.wiki/03-data-and-returns.md）：
- 一次 valuation_run 锁定输入版本与公式版本，成功后才切换为当前版本。
- 行情修订或流水补录后重算，生成新 run；旧 run 保留可追溯。
- 同一 run 内日收益可加总为周/月收益；不同 run 的快照不能混用。
"""

from __future__ import annotations

import enum
import uuid

# 本模块有名为 date 的列，会遮蔽 datetime.date；用别名避免注解解析错误
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ledger.db.base import Base, TimestampMixin, UUIDPrimaryKey, enum_column


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"  # 已被更新的 run 取代


class Completeness(str, enum.Enum):
    """报表完整性。不能把缺数据的汇总标成完整总资产。"""

    COMPLETE = "complete"  # 全部持仓均有当日有效净值
    PARTIAL = "partial"  # 部分产品缺净值或存在冲突
    CARRIED_FORWARD = "carried_forward"  # 使用了之前净值作暂估
    STALE = "stale"  # 超出来源允许延迟
    MISSING = "missing"  # 无可用净值，金额为 null


class ValuationRun(Base, UUIDPrimaryKey, TimestampMixin):
    """一次收益计算。"""

    __tablename__ = "valuation_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    to_date: Mapped[date_type] = mapped_column(Date, nullable=False)

    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "run_status"),
        default=RunStatus.PENDING,
        nullable=False,
    )
    # 收益公式版本。公式调整后旧快照仍可解释。
    formula_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # 输入数据版本指纹（流水最大更新时间 + 行情 selection_version 等）
    input_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # 是否为该用户当前对外展示的版本
    is_current: Mapped[bool] = mapped_column(default=False, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(1024))


class PositionSnapshot(Base, UUIDPrimaryKey):
    """每个 (run, 账户, 产品, 日期) 的持仓估值。

    记录实际使用的净值及其日期，便于解释「这个收益是用哪天净值算的」。
    """

    __tablename__ = "position_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "account_id", "product_id", "date", name="uq_position_snapshots_identity"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("valuation_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False)

    shares: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    # 无可用净值时为 NULL，不能用 0 冒充
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    realized_pnl_cumulative: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)

    # 实际使用的净值引用及其归属日
    nav_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("observations.id")
    )
    nav_date: Mapped[date_type | None] = mapped_column(Date)
    quality: Mapped[Completeness] = mapped_column(
        enum_column(Completeness, "completeness"), nullable=False
    )


class PortfolioSnapshot(Base, UUIDPrimaryKey):
    """用户整体日快照。跨币种不求和，按币种分行。"""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "date", "currency", name="uq_portfolio_snapshots_identity"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("valuation_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    market_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    # 累计投资收益 P_t = M_t + R_t + D_t - B_t - F_t
    cumulative_pnl: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    # 当日收益 = 当日 P_t - 前一日 P_t
    period_pnl: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))

    completeness: Mapped[Completeness] = mapped_column(
        enum_column(Completeness, "completeness"), nullable=False
    )
    # 已估值产品数 / 持仓产品总数，用于前端提示
    valued_product_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_product_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
