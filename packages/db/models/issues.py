"""SEO issues (A-TO-Z-PLAN.md §Phase 3, §F).

Every technical/content finding is a row here. `normalized_key` (UNIQUE per project) makes
re-analysis idempotent — a re-detected issue UPDATEs `last_seen` + `status`, never a duplicate.
Evidence is attached via `evidence_links` (subject_type='issue')."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

SEVERITIES = ("critical", "high", "medium", "low", "info")
ISSUE_STATES = ("open", "acknowledged", "resolved", "wont_fix", "regressed")


class SeoIssue(Base, ProjectScopedMixin):
    __tablename__ = "seo_issues"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_key", name="uq_seo_issues_project_key"),
        Index("ix_seo_issues_project_sev", "project_id", "severity"),
        Index("ix_seo_issues_open", "project_id", "status"),
    )

    crawl_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    check_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # indexability / on_page / urls / links / schema / hreflang / crawlability / duplicates
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)                      # the affected URL, if page-level
    url_pattern: Mapped[str | None] = mapped_column(Text)              # for site-wide / templated issues
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    fix: Mapped[str | None] = mapped_column(Text)                     # human-readable remediation (advisory)
    normalized_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    detector_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.1.0")
    first_seen: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
