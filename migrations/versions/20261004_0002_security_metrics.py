"""Revocable sessions, source approvals and valuation v2 constraints.

Existing data must satisfy new ownership and current-run constraints; do not silently repair it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_security_metrics"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE auth_sessions (
user_id UUID NOT NULL,
token_hash VARCHAR(64) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL,
expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
revoked_at TIMESTAMP WITH TIME ZONE,
id UUID NOT NULL,
CONSTRAINT pk_auth_sessions PRIMARY KEY (id),
CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON
DELETE CASCADE,
CONSTRAINT uq_auth_sessions_token_hash UNIQUE (token_hash)
)"""
    )
    op.execute("CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)")
    op.execute(
        """CREATE TABLE allowed_domains (
hostname VARCHAR(253) NOT NULL,
approved_by UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
CONSTRAINT pk_allowed_domains PRIMARY KEY (hostname),
CONSTRAINT fk_allowed_domains_approved_by_users FOREIGN KEY(approved_by) REFERENCES users
(id)
)"""
    )
    op.execute(
        """CREATE TABLE source_proposals (
owner_id UUID NOT NULL,
product_id UUID NOT NULL,
source_id UUID,
display_name VARCHAR(128) NOT NULL,
current_version INTEGER NOT NULL,
id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
CONSTRAINT pk_source_proposals PRIMARY KEY (id),
CONSTRAINT fk_source_proposals_owner_id_users FOREIGN KEY(owner_id) REFERENCES users (id),
CONSTRAINT fk_source_proposals_product_id_products FOREIGN KEY(product_id) REFERENCES
products (id),
CONSTRAINT fk_source_proposals_source_id_data_sources FOREIGN KEY(source_id) REFERENCES
data_sources (id)
)"""
    )
    op.execute("CREATE INDEX ix_source_proposals_owner_id ON source_proposals (owner_id)")
    op.execute(
        """CREATE TABLE source_proposal_versions (
proposal_id UUID NOT NULL,
version INTEGER NOT NULL,
config JSONB NOT NULL,
config_hash VARCHAR(64) NOT NULL,
status VARCHAR(32) NOT NULL,
preview JSONB,
artifact_id UUID,
reviewed_by UUID,
reviewed_at TIMESTAMP WITH TIME ZONE,
review_note VARCHAR(512),
id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
CONSTRAINT pk_source_proposal_versions PRIMARY KEY (id),
CONSTRAINT uq_proposal_version UNIQUE (proposal_id, version),
CONSTRAINT fk_source_proposal_versions_proposal_id_source_proposals FOREIGN
KEY(proposal_id) REFERENCES source_proposals (id),
CONSTRAINT fk_source_proposal_versions_artifact_id_raw_artifacts FOREIGN KEY(artifact_id)
REFERENCES raw_artifacts (id),
CONSTRAINT fk_source_proposal_versions_reviewed_by_users FOREIGN KEY(reviewed_by)
REFERENCES users (id)
)"""
    )
    op.execute(
        """CREATE TABLE job_requests (
user_id UUID NOT NULL,
job_id UUID NOT NULL,
id UUID NOT NULL,
CONSTRAINT pk_job_requests PRIMARY KEY (id),
CONSTRAINT uq_job_requests_user_job UNIQUE (user_id, job_id),
CONSTRAINT fk_job_requests_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON
DELETE CASCADE,
CONSTRAINT fk_job_requests_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE
CASCADE
)"""
    )
    op.execute("CREATE INDEX ix_job_requests_user_id ON job_requests (user_id)")
    op.add_column("data_sources", sa.Column("source_key", sa.String(128), nullable=True))
    op.execute("UPDATE data_sources SET source_key = adapter_key || ':' || id::text")
    op.alter_column("data_sources", "source_key", nullable=False)
    op.drop_constraint("uq_data_sources_adapter_key", "data_sources", type_="unique")
    op.create_unique_constraint("uq_data_sources_source_key", "data_sources", ["source_key"])
    op.add_column("transactions", sa.Column("cycle_ref", postgresql.UUID(as_uuid=True)))
    op.add_column(
        "position_snapshots",
        sa.Column(
            "metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.alter_column("position_snapshots", "metrics", server_default=None)
    op.create_unique_constraint("uq_valuation_runs_user_id", "valuation_runs", ["user_id", "id"])
    op.create_index(
        "uq_current_valuation_user",
        "valuation_runs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_foreign_key(
        "fk_position_snapshot_user_run",
        "position_snapshots",
        "valuation_runs",
        ["user_id", "run_id"],
        ["user_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_position_snapshot_user_account",
        "position_snapshots",
        "bank_accounts",
        ["user_id", "account_id"],
        ["user_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_portfolio_snapshot_user_run",
        "portfolio_snapshots",
        "valuation_runs",
        ["user_id", "run_id"],
        ["user_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(op.f("ck_jobs_job_type"), "jobs", type_="check")
    op.create_check_constraint(
        "job_type",
        "jobs",
        "type IN "
        "('sync_product_nav','backfill_product_nav','recalc_portfolio','discover_products','preview_source','send_email')",
    )


def downgrade() -> None:
    # Refuse destructive downgrade while v2 source definitions or preview jobs remain.
    op.execute(
        """DO $$ BEGIN IF EXISTS (SELECT 1 FROM jobs WHERE type = 'preview_source') THEN RAISE
EXCEPTION 'Archive preview jobs before downgrade'; END IF; END $$"""
    )
    op.drop_constraint(op.f("ck_jobs_job_type"), "jobs", type_="check")
    op.create_check_constraint(
        "job_type",
        "jobs",
        "type IN "
        "('sync_product_nav','backfill_product_nav','recalc_portfolio','discover_products','send_email')",
    )
    op.drop_constraint("fk_portfolio_snapshot_user_run", "portfolio_snapshots", type_="foreignkey")
    op.drop_constraint(
        "fk_position_snapshot_user_account", "position_snapshots", type_="foreignkey"
    )
    op.drop_constraint("fk_position_snapshot_user_run", "position_snapshots", type_="foreignkey")
    op.drop_index("uq_current_valuation_user", table_name="valuation_runs")
    op.drop_constraint("uq_valuation_runs_user_id", "valuation_runs", type_="unique")
    op.drop_column("position_snapshots", "metrics")
    op.drop_column("transactions", "cycle_ref")
    op.create_unique_constraint("uq_data_sources_adapter_key", "data_sources", ["adapter_key"])
    op.drop_constraint("uq_data_sources_source_key", "data_sources", type_="unique")
    op.drop_column("data_sources", "source_key")
    op.drop_table("job_requests")
    op.drop_table("source_proposal_versions")
    op.drop_table("source_proposals")
    op.drop_table("allowed_domains")
    op.drop_table("auth_sessions")
