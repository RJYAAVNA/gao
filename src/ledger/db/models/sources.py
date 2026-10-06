"""Versioned private source proposals and explicit domain approvals."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ledger.db.base import Base, TimestampMixin, UUIDPrimaryKey


class AllowedDomain(Base, TimestampMixin):
    __tablename__ = "allowed_domains"
    hostname: Mapped[str] = mapped_column(String(253), primary_key=True)
    approved_by: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"))


class SourceProposal(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "source_proposals"
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("products.id"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("data_sources.id")
    )
    display_name: Mapped[str] = mapped_column(String(128))
    current_version: Mapped[int] = mapped_column(Integer, default=1)


class SourceProposalVersion(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "source_proposal_versions"
    __table_args__ = (UniqueConstraint("proposal_id", "version", name="uq_proposal_version"),)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("source_proposals.id")
    )
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, object]] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    preview: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("raw_artifacts.id")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(512))
