"""迁移与模型一致性测试。

不连接数据库：用 alembic 的离线模式（--sql）生成静态 SQL，
再与模型编译出的 DDL 逐项对比。

这是防止「改了模型忘记写迁移」的关卡。CI 里另有 `alembic check`
在真实数据库上做同样的校验。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from ledger.db.models import Base

DIALECT = postgresql.dialect()
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# alembic 自身的版本表，不属于业务 schema
INTERNAL_TABLES = {"alembic_version"}


def _split_top_level(inner: str) -> set[str]:
    """按顶层逗号切分 CREATE TABLE 的内容。

    括号内的逗号（如 NUMERIC(24, 8)、CHECK (x IN ('a','b'))）不切分，
    否则无法正确比较。
    """
    items: list[str] = []
    depth = 0
    buf = ""
    for ch in inner:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(buf)
    return {re.sub(r"\s+", " ", it).strip() for it in items if it.strip()}


def _parse_create_table(ddl: str) -> tuple[str, set[str]]:
    """解析 CREATE TABLE 语句为 (表名, 列与约束条目集合)。"""
    match = re.match(r"\s*CREATE TABLE (\w+) \((.*)\)\s*;?\s*$", ddl.strip(), re.S)
    assert match is not None, f"无法解析 DDL: {ddl[:80]}"
    return match.group(1), _split_top_level(match.group(2))


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """用 alembic 离线模式生成建表 SQL。

    环境变量里的 DATABASE_URL 不需要真实可连接：--sql 模式不建立连接。
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic 离线生成失败:\n{result.stderr[-2000:]}")
    return result.stdout


@pytest.fixture(scope="module")
def migration_tables(migration_sql: str) -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for match in re.finditer(r"CREATE TABLE \w+ \(.*?\n\);", migration_sql, re.S):
        name, items = _parse_create_table(match.group(0))
        tables[name] = items
    return tables


def test_migration_covers_all_model_tables(migration_tables: dict[str, set[str]]) -> None:
    """模型里的每张表都必须出现在迁移中。"""
    model_tables = set(Base.metadata.tables)
    migrated = set(migration_tables) - INTERNAL_TABLES
    assert model_tables - migrated == set(), f"迁移缺少表: {model_tables - migrated}"
    assert migrated - model_tables == set(), f"迁移多出表: {migrated - model_tables}"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_table_definition_matches_model(
    table_name: str, migration_tables: dict[str, set[str]]
) -> None:
    """逐表比较列与约束。顺序无关，内容必须完全一致。"""
    expected_name, expected = _parse_create_table(
        str(CreateTable(Base.metadata.tables[table_name]).compile(dialect=DIALECT))
    )
    assert expected_name == table_name

    actual = migration_tables.get(table_name)
    assert actual is not None, f"迁移中没有 {table_name}"

    only_model = expected - actual
    only_migration = actual - expected
    assert not only_model, f"{table_name} 模型有而迁移没有: {sorted(only_model)}"
    assert not only_migration, f"{table_name} 迁移有而模型没有: {sorted(only_migration)}"


def test_migration_creates_all_indexes(migration_sql: str) -> None:
    """模型声明的索引都要在迁移里创建。"""
    expected_indexes = {ix.name for table in Base.metadata.tables.values() for ix in table.indexes}
    created = set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", migration_sql))
    assert expected_indexes - created == set(), f"迁移缺少索引: {expected_indexes - created}"


def test_downgrade_drops_everything() -> None:
    """downgrade 必须删除所有表，否则回滚后残留对象会阻碍重新升级。"""
    versions = PROJECT_ROOT / "migrations" / "versions"
    initial = next(versions.glob("*0001_initial*.py"))
    source = initial.read_text(encoding="utf-8")

    downgrade_part = source.split("def downgrade()")[1]
    dropped = set(re.findall(r'op\.drop_table\("(\w+)"\)', downgrade_part))
    assert (
        set(Base.metadata.tables) == dropped
    ), f"downgrade 未删除: {set(Base.metadata.tables) - dropped}"


def test_migration_has_no_hardcoded_credentials() -> None:
    """迁移文件不得包含连接串或明文凭据。

    注意 password_hash 是合法列名，这里只匹配真正的凭据写法。
    """
    # 连接串、赋值形式的密码、以及旧版 compose 里出现过的默认口令
    forbidden = [
        re.compile(r"postgresql://[^\s\"']+"),
        re.compile(r"""(?:password|passwd|secret|token)\s*=\s*["'][^"']+["']""", re.I),
        re.compile(r"19950521"),  # 旧版默认密码，确保没被带进来
    ]
    versions = PROJECT_ROOT / "migrations" / "versions"
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            match = pattern.search(text)
            assert match is None, f"{path.name} 疑似含凭据: {match.group(0)[:40]!r}"
