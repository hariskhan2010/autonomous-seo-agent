"""Crawl system + the evidence store (A-TO-Z-PLAN.md §Phase 2, §F).

`page_snapshots` is *the* evidence store — raw HTML / rendered DOM / headers live in object
storage, this table holds the hash + pointer + metadata. Every later finding cites one.
`tool_calls` is the always-on audit row for every registered-tool invocation (§I) — it also
carries LLM token/cost so it doubles as the cost meter deferred from Phase 1."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin, TenantMixin

CRAWL_TIERS = ("http", "browser", "advanced", "sitemap")
CRAWL_STATES = ("queued", "running", "completed", "failed", "partial")


class CrawlRun(Base, ProjectScopedMixin):
    __tablename__ = "crawl_runs"
    __table_args__ = (Index("ix_crawl_runs_tenant_project", "tenant_id", "project_id"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    tier_requested: Mapped[str] = mapped_column(String(12), nullable=False, default="http")
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class PageSnapshot(Base, ProjectScopedMixin):
    """Immutable, content-addressed. A new capture of the same URL with different bytes is a
    new row + new hash, never an overwrite."""

    __tablename__ = "page_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_hash", name="uq_page_snapshots_hash"),
        Index("ix_page_snapshots_url", "project_id", "url_hash"),
    )

    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    final_url: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(String(12), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 of raw body
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))   # simhash (near-dup)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # object-storage keys
    raw_key: Mapped[str | None] = mapped_column(Text)
    rendered_key: Mapped[str | None] = mapped_column(Text)
    headers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    redirect_chain: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")


class CrawlResult(Base, ProjectScopedMixin):
    """Parsed, structured view of one snapshot — what the technical/content engines consume."""

    __tablename__ = "crawl_results"
    __table_args__ = (
        UniqueConstraint("crawl_run_id", "url_hash", name="uq_crawl_results_run_url"),
        Index("ix_crawl_results_tenant_project", "tenant_id", "project_id"),
    )

    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("page_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    canonical: Mapped[str | None] = mapped_column(Text)
    robots_meta: Mapped[str | None] = mapped_column(String(120))
    h1: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    internal_links: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    external_links: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    images: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    headings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    schema_blocks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    hreflang: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    changed_since_last: Mapped[bool] = mapped_column(nullable=False, default=True)


class ToolCall(Base, TenantMixin):
    """Every registered-tool invocation (A-TO-Z-PLAN.md §I). Also the LLM cost meter (§L)."""

    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_tool_calls_created", "tenant_id", "created_at"),)

    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    tool: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    tool_version: Mapped[str] = mapped_column(String(20), nullable=False)
    caller: Mapped[str | None] = mapped_column(String(60))  # agent name, or "system"
    risk: Mapped[str] = mapped_column(String(24), nullable=False)
    inputs_hash: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok/error/blocked
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # LLM cost meter fields (null for non-LLM tools)
    llm_role: Mapped[str | None] = mapped_column(String(16))
    llm_provider: Mapped[str | None] = mapped_column(String(40))
    llm_model: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
