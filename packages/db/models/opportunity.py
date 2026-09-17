"""Opportunity engine models (A-TO-Z-PLAN.md §Phase 7, §24–25, §50).

`normalized_key` UNIQUE per project → re-detection UPDATEs (status, last_seen, evidence) instead
of inserting. An opportunity with zero `evidence_links` (subject_type='opportunity') is rejected."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

OPPORTUNITY_TYPES = (
    "fix_technical_issue", "add_internal_links", "consolidate_cannibalization",
    "refresh_decayed_content", "fill_content_gap", "target_keyword_gap",
    "improve_thin_content", "add_schema", "fix_canonical",
)
PRIORITIES = ("P0", "P1", "P2", "P3")
OPPORTUNITY_STATES = (
    "detected", "analyzing", "planned", "awaiting_approval", "approved",
    "executing", "verifying", "completed", "failed", "rolled_back", "ignored",
)
ACTION_CLASSES = ("READ_ONLY", "LOW_RISK_WRITE", "HIGH_RISK_WRITE", "IRREVERSIBLE_EXTERNAL_ACTION")


class Opportunity(Base, ProjectScopedMixin):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_key", name="uq_opportunities_project_key"),
        Index("ix_opportunities_priority", "project_id", "priority", "status"),
    )

    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    normalized_key: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    url_pattern: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)

    business_impact: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0.5)
    seo_impact: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0.5)
    feasibility: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0.5)
    risk: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0.3)
    score: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=0.0)
    priority: Mapped[str] = mapped_column(String(2), nullable=False, default="P3")

    action_class: Mapped[str] = mapped_column(String(28), nullable=False, default="LOW_RISK_WRITE")
    recommendation: Mapped[str | None] = mapped_column(Text)
    proposed_change: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    verification_method: Mapped[str | None] = mapped_column(Text)
    expected_outcome: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="detected")
    detector: Mapped[str] = mapped_column(String(40), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.1.0")
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
