"""SERP runs / results / features (A-TO-Z-PLAN.md §Phase 4, §10).

Every SERP pull is an evidence source: the raw provider payload goes to object storage, a
`page_snapshots`-style hash lives on `serp_runs`, and an `evidence` row (kind='serp_snapshot')
points at it."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

SERP_FEATURE_TYPES = (
    "featured_snippet", "people_also_ask", "related_searches", "video", "image_pack",
    "top_stories", "local_pack", "shopping", "ai_overview", "knowledge_panel", "sitelinks",
    "reviews", "twitter",
)


class SerpRun(Base, ProjectScopedMixin):
    __tablename__ = "serp_runs"
    __table_args__ = (Index("ix_serp_runs_tenant_project", "tenant_id", "project_id"),)

    query: Mapped[str] = mapped_column(Text, nullable=False)
    keyword_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-US")
    device: Mapped[str] = mapped_column(String(8), nullable=False, default="desktop")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_key: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class SerpResult(Base, ProjectScopedMixin):
    __tablename__ = "serp_results"
    __table_args__ = (
        UniqueConstraint("serp_run_id", "position", name="uq_serp_results_run_pos"),
        Index("ix_serp_results_domain", "project_id", "domain"),
    )

    serp_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("serp_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    is_own: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_competitor: Mapped[bool] = mapped_column(nullable=False, default=False)


class SerpFeature(Base, ProjectScopedMixin):
    __tablename__ = "serp_features"

    serp_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("serp_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_type: Mapped[str] = mapped_column(String(24), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class SerpEntity(Base, ProjectScopedMixin):
    __tablename__ = "serp_entities"

    serp_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("serp_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="topic")  # topic / question / brand
    weight: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=1.0)
