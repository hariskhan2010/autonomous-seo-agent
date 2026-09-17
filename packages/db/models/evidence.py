"""Evidence & provenance (A-TO-Z-PLAN.md §F.1, ADR-0006).

`evidence` is the canonical provenance record; `evidence_links` is the polymorphic M:N that lets
many evidence rows back one issue / opportunity / kg_edge / agent_decision / verification /
learning. A finding with zero links is rejected (service check + partial index guard later)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

EVIDENCE_KINDS = (
    "http_response", "rendered_dom", "gsc_row", "ga4_row", "serp_snapshot", "ai_response",
    "sitemap", "robots", "pagespeed", "rich_results", "competitor_snapshot", "log_line",
)
SUBJECT_TYPES = (
    "issue", "opportunity", "recommendation", "kg_edge", "agent_decision", "verification", "learning",
)


class Evidence(Base, ProjectScopedMixin):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_hash", "kind", name="uq_evidence_hash_kind"),
        CheckConstraint(f"kind IN {EVIDENCE_KINDS!r}", name="kind_allowed"),
        Index("ix_evidence_tenant_project", "tenant_id", "project_id"),
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(String(8))
    http_status: Mapped[int | None] = mapped_column()

    crawl_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    serp_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    ai_prompt_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # object-storage pointer

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(40))
    parser: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str | None] = mapped_column(String(40))
    collected_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class EvidenceLink(Base, ProjectScopedMixin):
    __tablename__ = "evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "evidence_id", "subject_type", "subject_id", name="uq_evidence_link_subject"
        ),
        CheckConstraint(f"subject_type IN {SUBJECT_TYPES!r}", name="subject_type_allowed"),
    )

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)
