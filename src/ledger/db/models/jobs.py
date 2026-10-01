"""持久任务队列。

实现依据：PostgreSQL 的 SELECT ... FOR UPDATE SKIP LOCKED。
设计要点（对应 repo.wiki/02-architecture.md「任务可靠性」）：
- 领取在短事务中完成，网络请求发生在事务外。
- 租约 + 递增 lease_version：旧 worker 不得覆盖新 worker 的结果。
- 接受「至少一次执行」，靠唯一约束保证业务效果幂等。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ledger.db.base import Base, TimestampMixin, UUIDPrimaryKey, enum_column


class JobType(str, enum.Enum):
    SYNC_PRODUCT_NAV = "sync_product_nav"  # 采集单个产品净值
    BACKFILL_PRODUCT_NAV = "backfill_product_nav"  # 补数指定区间
    RECALC_PORTFOLIO = "recalc_portfolio"  # 重算用户快照
    DISCOVER_PRODUCTS = "discover_products"  # 来源产品目录发现
    SEND_EMAIL = "send_email"  # 验证邮件等


class JobStatus(str, enum.Enum):
    """任务状态机。

    partial / needs_review / needs_action 与 failed 分开：
    登录态失效或格式变化需要人工处理，不能无限重试。
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"  # 部分成功（如分页中途失败）
    RETRY_WAIT = "retry_wait"  # 等待退避后重试
    NEEDS_REVIEW = "needs_review"  # 数据存疑，待人工复核
    NEEDS_ACTION = "needs_action"  # 需人工介入（凭据失效、格式变化）
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorType(str, enum.Enum):
    """错误分类。决定是否重试以及退避策略。"""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"  # 429
    SERVER_ERROR = "server_error"  # 5xx
    PARSE_ERROR = "parse_error"  # 页面/接口格式变化
    VALIDATION_ERROR = "validation_error"  # 字段校验失败
    AUTH_EXPIRED = "auth_expired"
    CONFLICT = "conflict"  # 多来源数据冲突
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


class Job(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        # 去重键：普通重复触发复用活跃任务，显式补数用新的 generation
        UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),
        # worker 领取任务的核心索引
        Index("ix_jobs_claim", "status", "run_after", "priority"),
    )

    type: Mapped[JobType] = mapped_column(enum_column(JobType, "job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, "job_status"),
        default=JobStatus.QUEUED,
        nullable=False,
    )

    # 形如 sync_product_nav:{source_id}:{product_id}:{slot}:{range}:{generation}
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # 任务载荷显式带版本，升级期间 worker 能识别当前和上一版本
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    # 退避后的最早可执行时间
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 租约：worker 领取后设置，心跳续租，到期可被重领
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 每次领取递增。提交结果时必须匹配当前值，否则拒绝（旧 worker 保护）
    lease_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(64))

    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # 触发者：用户手工触发时记录，便于只展示本人发起的任务
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # 关联来源与产品，便于按来源限流和故障隔离
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE")
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )

    attempts: Mapped[list[JobAttempt]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobAttempt(Base, UUIDPrimaryKey):
    """每次尝试单独记录，不用一段截断文本承载所有结果。"""

    __tablename__ = "job_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt", name="uq_job_attempts_job_attempt"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    # 该次尝试对应的租约版本
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[JobStatus] = mapped_column(enum_column(JobStatus, "job_status"), nullable=False)
    error_type: Mapped[ErrorType | None] = mapped_column(enum_column(ErrorType, "error_type"))
    # 简短错误信息，不含凭据或用户金额
    error_message: Mapped[str | None] = mapped_column(String(1024))

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 结构化结果：写入记录数、分页游标、跳过数等
    result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(64))

    job: Mapped[Job] = relationship(back_populates="attempts")


class ScheduleWatermark(Base, TimestampMixin):
    """调度水位。

    停机期间漏掉的周期靠这个补发，避免「重启后不知道该补哪些」。
    """

    __tablename__ = "schedule_watermarks"

    # 调度项标识，如 nightly_sync:{source_id}
    schedule_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    # 已成功生成任务的最后一个调度时点
    last_scheduled_slot: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
