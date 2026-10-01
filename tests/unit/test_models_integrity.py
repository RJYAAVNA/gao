"""模型结构约束测试。

这些断言锁定 wiki 里定下的数据完整性设计，防止后续重构时被无意改掉。
不需要数据库连接，只检查 SQLAlchemy 元数据。
"""

from __future__ import annotations

from sqlalchemy import Numeric

from ledger.db.models import BankAccount, Base, Position, Transaction


def test_all_tables_registered() -> None:
    """模型必须全部注册到 metadata，否则 Alembic 自动生成会漏表。"""
    expected = {
        "users",
        "email_tokens",
        "audit_events",
        "institutions",
        "products",
        "product_distributions",
        "data_sources",
        "product_source_mappings",
        "raw_artifacts",
        "observations",
        "observation_heads",
        "manual_nav_submissions",
        "bank_accounts",
        "transactions",
        "positions",
        "import_batches",
        "valuation_runs",
        "position_snapshots",
        "portfolio_snapshots",
        "jobs",
        "job_attempts",
        "schedule_watermarks",
    }
    actual = set(Base.metadata.tables)
    assert expected <= actual, f"缺少表: {expected - actual}"


def test_bank_accounts_has_composite_unique_for_ownership() -> None:
    """(user_id, id) 唯一约束是用户隔离的数据库级基础。

    没有它，transactions 的复合外键无法建立。
    """
    constraint_cols = {
        tuple(c.name for c in uc.columns)
        for uc in BankAccount.__table__.constraints
        if hasattr(uc, "columns")
    }
    assert ("user_id", "id") in constraint_cols


def test_transactions_account_fk_includes_user_id() -> None:
    """交易的账户外键必须带 user_id，否则能把自己的流水绑到别人账户。"""
    composite_fks = [
        fk for fk in Transaction.__table__.foreign_key_constraints if len(fk.columns) == 2
    ]
    assert composite_fks, "transactions 缺少复合外键约束"

    cols = {tuple(sorted(c.name for c in fk.columns)) for fk in composite_fks}
    assert ("account_id", "user_id") in cols


def test_positions_account_fk_includes_user_id() -> None:
    composite_fks = [
        fk for fk in Position.__table__.foreign_key_constraints if len(fk.columns) == 2
    ]
    assert composite_fks, "positions 缺少复合外键约束"


def test_money_columns_use_numeric_not_float() -> None:
    """金额、份额、净值一律 NUMERIC。浮点累计金额会产生偏差。"""
    money_like = {
        "shares",
        "shares_delta",
        "cash_amount",
        "fee",
        "cost",
        "remaining_cost",
        "total_cost",
        "market_value",
        "unrealized_pnl",
        "realized_pnl",
        "realized_pnl_cumulative",
        "cumulative_pnl",
        "period_pnl",
        "value",
    }
    offenders: list[str] = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if col.name in money_like and not isinstance(col.type, Numeric):
                offenders.append(f"{table.name}.{col.name} = {col.type}")
    assert not offenders, f"以下金额字段未使用 NUMERIC: {offenders}"


def test_timestamps_are_timezone_aware() -> None:
    """时间戳必须带时区（timestamptz），存 UTC。"""
    offenders: list[str] = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            is_datetime = col.type.__class__.__name__ == "DateTime"
            if is_datetime and not getattr(col.type, "timezone", False):
                offenders.append(f"{table.name}.{col.name}")
    assert not offenders, f"以下时间戳缺少时区: {offenders}"


def test_observations_unique_includes_revision() -> None:
    """观测值唯一键必须含 revision，否则无法保留修订历史。"""
    table = Base.metadata.tables["observations"]
    uniques = {
        tuple(c.name for c in uc.columns) for uc in table.constraints if hasattr(uc, "columns")
    }
    target = ("product_id", "source_id", "valuation_date", "metric_type", "revision")
    assert target in uniques


def test_jobs_dedupe_key_unique() -> None:
    """去重键唯一，保证重复点击同步不产生重复任务。"""
    table = Base.metadata.tables["jobs"]
    uniques = {
        tuple(c.name for c in uc.columns) for uc in table.constraints if hasattr(uc, "columns")
    }
    assert ("dedupe_key",) in uniques
