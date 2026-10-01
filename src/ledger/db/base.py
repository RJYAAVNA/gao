"""ORM 基类与共享列类型。

精度约定（对应 repo.wiki/03-data-and-returns.md）：
- 金额 NUMERIC(24,8)，份额与净值 NUMERIC(28,12)。
- 一律用 Python Decimal，禁止 float 参与金额计算。
- 时间戳存 UTC（timestamptz），业务日期用 date 并按 Asia/Shanghai 解释。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import DateTime, Enum, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 枚举列统一长度。
# SQLAlchemy 默认按当前最长枚举值定长（如 VARCHAR(5)），
# 之后新增更长的取值会超出列宽而插入失败。统一留足余量，
# 让枚举增值不需要 ALTER TABLE。
ENUM_LENGTH = 32

# 统一命名约定，让 Alembic 生成的约束名可预测、迁移可回滚。
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---------------------------------------------------------------- 列类型别名
# 金额：总支出、赎回收入、费用、市值等
Money = Annotated[Decimal, mapped_column(Numeric(24, 8))]
# 份额与净值：需要更高小数位，银行净值常见 6 位，预留到 12 位
Shares = Annotated[Decimal, mapped_column(Numeric(28, 12))]
NavValue = Annotated[Decimal, mapped_column(Numeric(28, 12))]


def enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    """构造枚举列类型。

    三个关键参数：
    - native_enum=False：用 VARCHAR + CHECK 而非 PostgreSQL 原生类型，
      新增枚举值只需改 CHECK，不必 ALTER TYPE，迁移与回滚都更简单。
    - length=ENUM_LENGTH：避免按当前最长值定宽，枚举增值无需 ALTER。
    - values_callable：让数据库存枚举的「值」（如 'bank'）而非成员名
      （'BANK'）。不设这个参数，CHECK 约束会按成员名生成，而 ORM 写入的
      是值，插入必然违反约束。
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        # SQLAlchemy 1.4 起默认不生成 CHECK，显式打开以获得数据库层校验
        create_constraint=True,
        length=ENUM_LENGTH,
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )


def uuid_pk() -> uuid.UUID:
    """主键默认值。在应用侧生成，避免依赖数据库扩展。"""
    return uuid.uuid4()


class UUIDPrimaryKey:
    """UUID 主键 mixin。"""

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)


class TimestampMixin:
    """创建与更新时间，均为 UTC。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
