"""公共产品目录与数据源配置。

两个维度必须分开（对应 repo.wiki/README.md「多银行」说明）：
- 发行机构（理财子公司，如中银理财）：决定产品本身和净值。
- 销售银行（如中国银行）：决定销售渠道代码，同一产品可多渠道销售。
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ledger.db.base import Base, TimestampMixin, UUIDPrimaryKey, enum_column


class InstitutionType(str, enum.Enum):
    BANK = "bank"  # 销售银行
    ISSUER = "issuer"  # 理财发行机构（理财子公司）


class Institution(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "institutions"
    __table_args__ = (
        UniqueConstraint("name", "institution_type", name="uq_institutions_name_type"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    institution_type: Mapped[InstitutionType] = mapped_column(
        enum_column(InstitutionType, "institution_type"), nullable=False
    )
    # 中国理财网机构编码（如 C10102），用于对接官方登记平台
    official_org_code: Mapped[str | None] = mapped_column(String(32), index=True)


class ValuationMethod(str, enum.Enum):
    """估值方式决定能否套用「份额 × 单位净值」公式。"""

    NET_VALUE = "net_value"  # 净值型：可用单位净值估值
    CASH_MANAGEMENT = "cash_management"  # 现金管理类：万份收益/七日年化，第一版不纳入净值计算
    UNKNOWN = "unknown"


class Product(Base, UUIDPrimaryKey, TimestampMixin):
    """理财产品（公共数据，不含任何用户份额）。"""

    __tablename__ = "products"
    __table_args__ = (
        # 同一发行机构内，产品代码 + 份额类别 唯一
        UniqueConstraint("issuer_id", "issuer_code", "share_class", name="uq_products_issuer_code"),
    )

    issuer_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False
    )
    # 发行机构内部产品代码，如中银的 WFZDJQRKA
    issuer_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # 份额类别必须非空，用 'DEFAULT' 表示无分类，避免 NULL 破坏唯一约束
    share_class: Mapped[str] = mapped_column(String(16), default="DEFAULT", nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    valuation_method: Mapped[ValuationMethod] = mapped_column(
        enum_column(ValuationMethod, "valuation_method"),
        default=ValuationMethod.NET_VALUE,
        nullable=False,
    )
    # 最短持有天数，用于前端分类展示；NULL 表示未知
    min_holding_days: Mapped[int | None] = mapped_column(Integer)
    # 全国银行业理财登记托管中心登记编码，如 Z7001026000510。
    # 跨机构唯一标识，是对接中国理财网的关键。
    registration_code: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)

    issuer: Mapped[Institution] = relationship()
    distributions: Mapped[list[ProductDistribution]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductDistribution(Base, UUIDPrimaryKey, TimestampMixin):
    """销售渠道映射：同一产品在不同银行有不同销售代码。"""

    __tablename__ = "product_distributions"
    __table_args__ = (
        UniqueConstraint("bank_id", "channel_code", name="uq_product_distributions_bank_channel"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    bank_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("institutions.id"), nullable=False
    )
    channel_code: Mapped[str] = mapped_column(String(64), nullable=False)

    product: Mapped[Product] = relationship(back_populates="distributions")
    bank: Mapped[Institution] = relationship()


class DataSource(Base, UUIDPrimaryKey, TimestampMixin):
    """采集数据源配置。

    URL 由受控配置定义，不接受用户任意输入，避免 SSRF。
    """

    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("source_key", name="uq_data_sources_source_key"),)

    # 适配器标识，对应 collectors/registry.py 里注册的实现，如 'bocwm'、'chinawealth'
    source_key: Mapped[str] = mapped_column(
        String(128), default=lambda: str(uuid.uuid4()), nullable=False
    )
    adapter_key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("institutions.id")
    )
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 优先级越小越优先。多来源冲突时用于选择当前有效值。
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # 采集参数：并发上限、请求间隔、超时、公布时限、重试次数等
    config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 连续失败计数，超过阈值可自动暂停该来源并告警
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    institution: Mapped[Institution | None] = relationship()


class ProductSourceMapping(Base, UUIDPrimaryKey, TimestampMixin):
    """产品在某数据源中的标识。

    必须显式映射，不允许按产品名模糊匹配后直接入账。
    """

    __tablename__ = "product_source_mappings"
    __table_args__ = (
        UniqueConstraint("source_id", "source_product_id", name="uq_psm_source_product"),
        UniqueConstraint("product_id", "source_id", name="uq_psm_product_source"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    # 该来源内的产品标识，可能是产品代码也可能是来源内部 ID
    source_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    product: Mapped[Product] = relationship()
    source: Mapped[DataSource] = relationship()
