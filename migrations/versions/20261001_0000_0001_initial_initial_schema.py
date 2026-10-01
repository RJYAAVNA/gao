"""initial schema

建立全部 22 张表：身份与审计、公共产品目录、数据源配置、行情观测与修订、
用户私有持仓与流水、估值快照、持久任务队列。

设计依据见 repo.wiki/03-data-and-returns.md：
- 金额 NUMERIC(24,8)，份额与净值 NUMERIC(28,12)，不用浮点
- 时间戳 timestamptz 存 UTC，业务日期用 date
- 枚举用 VARCHAR + CHECK（非原生类型），列宽统一 32 便于增值
- transactions / positions 用复合外键 (user_id, account_id) 强制用户隔离

建表顺序由 SQLAlchemy 的拓扑排序给出，保证外键引用的表先建；
downgrade 按相反顺序删除。

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "institutions",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "institution_type",
            sa.Enum(
                "bank",
                "issuer",
                name="institution_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("official_org_code", sa.String(length=32), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_institutions"),
        sa.UniqueConstraint("name", "institution_type", name="uq_institutions_name_type"),
    )
    op.create_index(
        "ix_institutions_official_org_code", "institutions", ["official_org_code"], unique=False
    )

    op.create_table(
        "schedule_watermarks",
        sa.Column("schedule_key", sa.String(length=128), nullable=False),
        sa.Column("last_scheduled_slot", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("schedule_key", name="pk_schedule_watermarks"),
    )

    op.create_table(
        "users",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "admin",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "active",
                "suspended",
                "disabled",
                name="user_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    op.create_table(
        "audit_events",
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("before_ref", sa.String(length=128), nullable=True),
        sa.Column("after_ref", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_events_actor_id_users", ondelete="SET NULL"
        ),
    )

    op.create_table(
        "bank_accounts",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=64), nullable=False),
        sa.Column("masked_account", sa.String(length=32), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bank_accounts"),
        sa.ForeignKeyConstraint(
            ["bank_id"], ["institutions.id"], name="fk_bank_accounts_bank_id_institutions"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_bank_accounts_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "alias", name="uq_bank_accounts_user_alias"),
        sa.UniqueConstraint("user_id", "id", name="uq_bank_accounts_user_id_id"),
    )
    op.create_index("ix_bank_accounts_user_id", "bank_accounts", ["user_id"], unique=False)

    op.create_table(
        "data_sources",
        sa.Column("adapter_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_data_sources"),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_data_sources_institution_id_institutions",
        ),
        sa.UniqueConstraint("adapter_key", name="uq_data_sources_adapter_key"),
    )

    op.create_table(
        "email_tokens",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "verify_email",
                "reset_password",
                name="token_purpose",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_email_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_email_tokens_token_hash"),
    )

    op.create_table(
        "products",
        sa.Column("issuer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer_code", sa.String(length=64), nullable=False),
        sa.Column("share_class", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "valuation_method",
            sa.Enum(
                "net_value",
                "cash_management",
                "unknown",
                name="valuation_method",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("min_holding_days", sa.Integer(), nullable=True),
        sa.Column("registration_code", sa.String(length=32), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.ForeignKeyConstraint(
            ["issuer_id"], ["institutions.id"], name="fk_products_issuer_id_institutions"
        ),
        sa.UniqueConstraint(
            "issuer_id", "issuer_code", "share_class", name="uq_products_issuer_code"
        ),
    )
    op.create_index("ix_products_registration_code", "products", ["registration_code"], unique=True)

    op.create_table(
        "valuation_runs",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "superseded",
                name="run_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("formula_version", sa.String(length=32), nullable=False),
        sa.Column("input_version", sa.String(length=64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_valuation_runs"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_valuation_runs_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_valuation_runs_user_id", "valuation_runs", ["user_id"], unique=False)

    op.create_table(
        "jobs",
        sa.Column(
            "type",
            sa.Enum(
                "sync_product_nav",
                "backfill_product_nav",
                "recalc_portfolio",
                "discover_products",
                "send_email",
                name="job_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "partial",
                "retry_wait",
                "needs_review",
                "needs_action",
                "failed",
                "cancelled",
                name="job_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_version", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name="fk_jobs_source_id_data_sources",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_jobs_product_id_products", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], name="fk_jobs_requested_by_users", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "run_after", "priority"], unique=False)

    op.create_table(
        "portfolio_snapshots",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("market_value", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("total_cost", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("cumulative_pnl", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("period_pnl", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column(
            "completeness",
            sa.Enum(
                "complete",
                "partial",
                "carried_forward",
                "stale",
                "missing",
                name="completeness",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("valued_product_count", sa.Integer(), nullable=False),
        sa.Column("total_product_count", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_portfolio_snapshots"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["valuation_runs.id"],
            name="fk_portfolio_snapshots_run_id_valuation_runs",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "date", "currency", name="uq_portfolio_snapshots_identity"),
    )
    op.create_index(
        "ix_portfolio_snapshots_user_id", "portfolio_snapshots", ["user_id"], unique=False
    )

    op.create_table(
        "positions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shares", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("remaining_cost", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("ledger_version", sa.Integer(), nullable=False),
        sa.Column("last_transaction_date", sa.Date(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_positions"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_positions_product_id_products"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["bank_accounts.user_id", "bank_accounts.id"],
            name="fk_positions_user_account",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "account_id", "product_id", name="uq_positions_identity"),
    )
    op.create_index("ix_positions_user_id", "positions", ["user_id"], unique=False)

    op.create_table(
        "product_distributions",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_code", sa.String(length=64), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_distributions"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_distributions_product_id_products",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bank_id"], ["institutions.id"], name="fk_product_distributions_bank_id_institutions"
        ),
        sa.UniqueConstraint(
            "bank_id", "channel_code", name="uq_product_distributions_bank_channel"
        ),
    )

    op.create_table(
        "product_source_mappings",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_product_id", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_source_mappings"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name="fk_product_source_mappings_source_id_data_sources",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_source_mappings_product_id_products",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("source_id", "source_product_id", name="uq_psm_source_product"),
        sa.UniqueConstraint("product_id", "source_id", name="uq_psm_product_source"),
    )

    op.create_table(
        "raw_artifacts",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "api_json",
                "html",
                "screenshot",
                "user_upload",
                name="artifact_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_context", sa.String(length=1024), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_raw_artifacts"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name="fk_raw_artifacts_source_id_data_sources",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_raw_artifacts_owner_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("source_id", "sha256", name="uq_raw_artifacts_source_sha"),
    )
    op.create_index("ix_raw_artifacts_sha256", "raw_artifacts", ["sha256"], unique=False)

    op.create_table(
        "import_batches",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "preview_ready",
                "confirmed",
                "rejected",
                "failed",
                name="import_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("mapping_version", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.String(length=1024), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_import_batches_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["raw_artifacts.id"],
            name="fk_import_batches_artifact_id_raw_artifacts",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("user_id", "file_sha256", name="uq_import_batches_user_file"),
    )
    op.create_index("ix_import_batches_user_id", "import_batches", ["user_id"], unique=False)

    op.create_table(
        "job_attempts",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "partial",
                "retry_wait",
                "needs_review",
                "needs_action",
                "failed",
                "cancelled",
                name="job_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "error_type",
            sa.Enum(
                "timeout",
                "rate_limited",
                "server_error",
                "parse_error",
                "validation_error",
                "auth_expired",
                "conflict",
                "not_found",
                "unknown",
                name="error_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_job_attempts"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_job_attempts_job_id_jobs", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("job_id", "attempt", name="uq_job_attempts_job_attempt"),
    )

    op.create_table(
        "observations",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column(
            "metric_type",
            sa.Enum(
                "unit_nav",
                "cumulative_nav",
                "ten_thousand_profit",
                "seven_day_annualized",
                name="metric_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "quality_status",
            sa.Enum(
                "verified",
                "pending_review",
                "disputed",
                "rejected",
                name="quality_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observations"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], name="fk_observations_source_id_data_sources"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["raw_artifacts.id"],
            name="fk_observations_artifact_id_raw_artifacts",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_observations_product_id_products",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "product_id",
            "source_id",
            "valuation_date",
            "metric_type",
            "revision",
            name="uq_observations_identity",
        ),
    )
    op.create_index(
        "ix_observations_valuation_date", "observations", ["valuation_date"], unique=False
    )

    op.create_table(
        "manual_nav_submissions",
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column(
            "metric_type",
            sa.Enum(
                "unit_nav",
                "cumulative_nav",
                "ten_thousand_profit",
                "seven_day_annualized",
                name="metric_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column(
            "review_status",
            sa.Enum(
                "verified",
                "pending_review",
                "disputed",
                "rejected",
                name="quality_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=512), nullable=True),
        sa.Column("resulting_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_manual_nav_submissions"),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name="fk_manual_nav_submissions_reviewed_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resulting_observation_id"],
            ["observations.id"],
            name="fk_manual_nav_submissions_resulting_observation_id_observations",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name="fk_manual_nav_submissions_submitted_by_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_manual_nav_submissions_product_id_products",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "observation_heads",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column(
            "metric_type",
            sa.Enum(
                "unit_nav",
                "cumulative_nav",
                "ten_thousand_profit",
                "seven_day_annualized",
                name="metric_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selection_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "product_id", "valuation_date", "metric_type", name="pk_observation_heads"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["observations.id"],
            name="fk_observation_heads_observation_id_observations",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_observation_heads_product_id_products",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "position_snapshots",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("shares", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("cost", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("market_value", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("realized_pnl_cumulative", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("nav_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("nav_date", sa.Date(), nullable=True),
        sa.Column(
            "quality",
            sa.Enum(
                "complete",
                "partial",
                "carried_forward",
                "stale",
                "missing",
                name="completeness",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_position_snapshots"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_position_snapshots_product_id_products"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["valuation_runs.id"],
            name="fk_position_snapshots_run_id_valuation_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["nav_observation_id"],
            ["observations.id"],
            name="fk_position_snapshots_nav_observation_id_observations",
        ),
        sa.UniqueConstraint(
            "run_id", "account_id", "product_id", "date", name="uq_position_snapshots_identity"
        ),
    )
    op.create_index(
        "ix_position_snapshots_user_id", "position_snapshots", ["user_id"], unique=False
    )

    op.create_table(
        "transactions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "opening_balance",
                "buy",
                "redeem",
                "cash_dividend",
                "reinvest_dividend",
                "fee",
                "reversal",
                name="transaction_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("shares_delta", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("cash_amount", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("fee", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reversal_of", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("linked_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["bank_accounts.user_id", "bank_accounts.id"],
            name="fk_transactions_user_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of"],
            ["transactions.id"],
            name="fk_transactions_reversal_of_transactions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_transactions_import_batch_id_import_batches",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_transaction_id"],
            ["transactions.id"],
            name="fk_transactions_linked_transaction_id_transactions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_transactions_product_id_products"
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_transactions_user_idem"),
    )
    op.create_index(
        "ix_transactions_effective_date", "transactions", ["effective_date"], unique=False
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transactions_effective_date", table_name="transactions")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_position_snapshots_user_id", table_name="position_snapshots")
    op.drop_table("position_snapshots")
    op.drop_table("observation_heads")
    op.drop_table("manual_nav_submissions")
    op.drop_index("ix_observations_valuation_date", table_name="observations")
    op.drop_table("observations")
    op.drop_table("job_attempts")
    op.drop_index("ix_import_batches_user_id", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_index("ix_raw_artifacts_sha256", table_name="raw_artifacts")
    op.drop_table("raw_artifacts")
    op.drop_table("product_source_mappings")
    op.drop_table("product_distributions")
    op.drop_index("ix_positions_user_id", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_portfolio_snapshots_user_id", table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_valuation_runs_user_id", table_name="valuation_runs")
    op.drop_table("valuation_runs")
    op.drop_index("ix_products_registration_code", table_name="products")
    op.drop_table("products")
    op.drop_table("email_tokens")
    op.drop_table("data_sources")
    op.drop_index("ix_bank_accounts_user_id", table_name="bank_accounts")
    op.drop_table("bank_accounts")
    op.drop_table("audit_events")
    op.drop_table("users")
    op.drop_table("schedule_watermarks")
    op.drop_index("ix_institutions_official_org_code", table_name="institutions")
    op.drop_table("institutions")
