"""公共行情：原始证据、观测值与当前有效值。

核心约束（对应 repo.wiki/03-data-and-returns.md）：
- 单位净值、累计净值、万份收益、七日年化是不同指标，不能互相替代。
- 观测值不覆盖：值或证据实质变化时生成新 revision，旧版本保留。
- 每个 (产品, 日期, 指标) 只有一个当前有效值，由 observation_heads 指向。
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
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ledger.db.base import Base, TimestampMixin, UUIDPrimaryKey, enum_column


class MetricType(str, enum.Enum):
    """行情指标类型。

    UNIT_NAV 用于净值型持仓估值；CUMULATIVE_NAV 不能直接乘份额当市值。
    """

    UNIT_NAV = "unit_nav"  # 单位净值
    CUMULATIVE_NAV = "cumulative_nav"  # 累计净值
    TEN_THOUSAND_PROFIT = "ten_thousand_profit"  # 万份收益
    SEVEN_DAY_ANNUALIZED = "seven_day_annualized"  # 七日年化


class QualityStatus(str, enum.Enum):
    """观测值质量状态。决定能否成为当前有效值。"""

    VERIFIED = "verified"  # 已校验，可作为有效值
    PENDING_REVIEW = "pending_review"  # 待人工复核（低置信度、异常跳变）
    DISPUTED = "disputed"  # 多来源冲突超出容差
    REJECTED = "rejected"  # 审核否决


class ArtifactKind(str, enum.Enum):
    API_JSON = "api_json"
    HTML = "html"
    SCREENSHOT = "screenshot"
    USER_UPLOAD = "user_upload"


class RawArtifact(Base, UUIDPrimaryKey):
    """原始证据。

    公开采集证据 owner_user_id 为 NULL；用户上传的账单必须绑定 user_id，
    且不能未经审核转为公共行情。
    """

    __tablename__ = "raw_artifacts"
    __table_args__ = (
        # 同一来源下相同内容不重复存储
        UniqueConstraint("source_id", "sha256", name="uq_raw_artifacts_source_sha"),
    )

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    kind: Mapped[ArtifactKind] = mapped_column(
        enum_column(ArtifactKind, "artifact_kind"), nullable=False
    )
    # 存储位置引用（本地路径或 OSS key），内容不入数据库
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 请求上下文（URL、入参），便于离线回放。不含凭据。
    request_context: Mapped[str | None] = mapped_column(String(1024))


class Observation(Base, UUIDPrimaryKey):
    """单条行情观测值。

    同一输入重试不产生新 revision（靠唯一约束保证幂等）；
    值或证据实质变化才递增 revision。
    """

    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "source_id",
            "valuation_date",
            "metric_type",
            "revision",
            name="uq_observations_identity",
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("data_sources.id"), nullable=False
    )

    # 净值归属日，不是抓取日期。中银接口的 releaseDate 需验证其业务含义。
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    metric_type: Mapped[MetricType] = mapped_column(
        enum_column(MetricType, "metric_type"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)

    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    quality_status: Mapped[QualityStatus] = mapped_column(
        enum_column(QualityStatus, "quality_status"),
        default=QualityStatus.VERIFIED,
        nullable=False,
    )

    # 来源公布时间（若来源提供），与抓取时间区分
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("raw_artifacts.id", ondelete="SET NULL")
    )
    # 解析器版本：解析逻辑修复后可定位并重放受影响记录
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # OCR/模糊解析的置信度，API 来源为 NULL
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    note: Mapped[str | None] = mapped_column(String(512))

    artifact: Mapped[RawArtifact | None] = relationship()


class ObservationHead(Base, TimestampMixin):
    """每个 (产品, 日期, 指标) 的当前有效值。

    这是估值计算唯一读取的行情表。原始 observations 不删除。
    """

    __tablename__ = "observation_heads"

    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
    )
    valuation_date: Mapped[date] = mapped_column(Date, primary_key=True)
    metric_type: Mapped[MetricType] = mapped_column(
        enum_column(MetricType, "metric_type"), primary_key=True
    )

    observation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("observations.id"), nullable=False
    )
    # 选择逻辑版本。来源优先级或容差规则调整后可重新选择并追溯。
    selection_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    observation: Mapped[Observation] = relationship()


class ManualNavSubmission(Base, UUIDPrimaryKey, TimestampMixin):
    """用户手工录入的净值候选。

    普通用户提交只是候选，必须管理员审核后才能改变公共行情，
    防止一个用户覆盖其他用户依赖的共享净值。
    """

    __tablename__ = "manual_nav_submissions"

    submitted_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_type: Mapped[MetricType] = mapped_column(
        enum_column(MetricType, "metric_type"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)

    review_status: Mapped[QualityStatus] = mapped_column(
        enum_column(QualityStatus, "quality_status"),
        default=QualityStatus.PENDING_REVIEW,
        nullable=False,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(512))
    # 审核通过后生成的观测值
    resulting_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("observations.id", ondelete="SET NULL")
    )
