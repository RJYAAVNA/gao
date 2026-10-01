"""DDL 生成测试。

不连接数据库，只用 PostgreSQL 方言把 schema 编译成 SQL，
确认模型定义能真正建表（类型、约束、外键都可编译）。
"""

from __future__ import annotations

import enum

import pytest
from sqlalchemy import Enum
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from ledger.db.base import ENUM_LENGTH
from ledger.db.models import Base

DIALECT = postgresql.dialect()


def _enum_columns() -> list[tuple[str, str, Enum]]:
    """收集全部枚举列，供参数化测试使用。"""
    found: list[tuple[str, str, Enum]] = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, Enum):
                found.append((table.name, col.name, col.type))
    return found


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_table_ddl_compiles(table_name: str) -> None:
    """每张表都能编译出 CREATE TABLE 语句。"""
    table = Base.metadata.tables[table_name]
    ddl = str(CreateTable(table).compile(dialect=DIALECT))
    assert f"CREATE TABLE {table_name}" in ddl


@pytest.mark.parametrize(("table", "column", "enum_type"), _enum_columns())
def test_enum_check_uses_values_not_member_names(table: str, column: str, enum_type: Enum) -> None:
    """CHECK 约束必须用枚举的值，不能用 Python 成员名。

    ORM 写入的是 member.value（如 'bank'）。若 CHECK 按成员名生成
    （'BANK'），每次插入都会违反约束——这种错误只在首次写库时才暴露。
    """
    enum_cls = enum_type.enum_class
    assert enum_cls is not None, f"{table}.{column} 未绑定枚举类"

    values = {m.value for m in enum_cls}
    names = {m.name for m in enum_cls}
    rendered = set(enum_type.enums)

    assert rendered == values, f"{table}.{column} CHECK 使用了 {rendered}，应为 {values}"
    # 仅当值与名字确实不同时才能断言不等（本项目的枚举值都是小写）
    if values != names:
        assert rendered != names


@pytest.mark.parametrize(("table", "column", "enum_type"), _enum_columns())
def test_enum_columns_have_room_to_grow(table: str, column: str, enum_type: Enum) -> None:
    """枚举列宽统一，避免新增更长取值时超出列宽。

    SQLAlchemy 默认按当前最长值定宽（如 VARCHAR(5)），
    之后加一个更长的状态就会插入失败。
    """
    assert enum_type.length == ENUM_LENGTH, f"{table}.{column} 列宽应为 {ENUM_LENGTH}"
    longest = max(len(m.value) for m in enum_type.enum_class or [])
    assert longest <= ENUM_LENGTH


def test_enum_check_constraints_present_in_ddl() -> None:
    """CHECK 约束要真正出现在 DDL 里（需要 create_constraint=True）。"""
    ddl = str(CreateTable(Base.metadata.tables["users"]).compile(dialect=DIALECT))
    assert "CHECK (role IN ('user', 'admin'))" in ddl
    assert "CHECK (status IN (" in ddl


def test_enum_values_are_lowercase_snake() -> None:
    """枚举值统一小写蛇形，避免数据库里出现大小写混用。"""
    offenders: list[str] = []
    seen: set[type[enum.Enum]] = set()
    for table, column, enum_type in _enum_columns():
        cls = enum_type.enum_class
        if cls is None or cls in seen:
            continue
        seen.add(cls)
        for member in cls:
            if member.value != member.value.lower():
                offenders.append(f"{table}.{column}:{member.value}")
    assert not offenders, f"以下枚举值不是小写: {offenders}"


def test_numeric_precision_in_ddl() -> None:
    """金额精度落到 DDL：NUMERIC(24, 8)，份额/净值 NUMERIC(28, 12)。"""
    ddl = str(CreateTable(Base.metadata.tables["transactions"]).compile(dialect=DIALECT))
    assert "NUMERIC(24, 8)" in ddl  # cash_amount / fee
    assert "NUMERIC(28, 12)" in ddl  # shares_delta


def test_timestamptz_in_ddl() -> None:
    """时间戳编译为 TIMESTAMP WITH TIME ZONE。"""
    ddl = str(CreateTable(Base.metadata.tables["users"]).compile(dialect=DIALECT))
    assert "TIMESTAMP WITH TIME ZONE" in ddl


def test_uuid_primary_key_in_ddl() -> None:
    ddl = str(CreateTable(Base.metadata.tables["users"]).compile(dialect=DIALECT))
    assert "id UUID NOT NULL" in ddl
    assert "PRIMARY KEY (id)" in ddl


def test_composite_fk_in_transactions_ddl() -> None:
    """复合外键必须出现在 DDL 中，这是用户隔离的数据库级保证。"""
    ddl = str(CreateTable(Base.metadata.tables["transactions"]).compile(dialect=DIALECT))
    assert "FOREIGN KEY(user_id, account_id)" in ddl
    assert "REFERENCES bank_accounts (user_id, id)" in ddl


def test_jobs_claim_index_exists() -> None:
    """worker 领取任务依赖的复合索引必须存在。"""
    table = Base.metadata.tables["jobs"]
    index_names = {ix.name for ix in table.indexes}
    assert "ix_jobs_claim" in index_names


def test_enums_rendered_as_varchar_with_check() -> None:
    """枚举用 native_enum=False：改枚举值不需要 ALTER TYPE，迁移更简单。"""
    ddl = str(CreateTable(Base.metadata.tables["jobs"]).compile(dialect=DIALECT))
    assert "VARCHAR" in ddl
    assert "CREATE TYPE" not in ddl


def test_full_schema_compiles() -> None:
    """整体 schema 可编译，且表数量符合预期。"""
    statements = [str(CreateTable(t).compile(dialect=DIALECT)) for t in Base.metadata.sorted_tables]
    assert len(statements) == len(Base.metadata.tables)
    assert len(statements) >= 22
