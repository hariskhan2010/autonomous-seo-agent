"""GEO / AI-search models (A-TO-Z-PLAN.md §Phase 10, §22–23).

Every AI-visibility datapoint keeps full context: provider, model, model_version, prompt_id +
prompt_version, locale, timestamp, raw_response_ref, parser + parser_version. A datapoint
without this context is not stored."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

PROMPT_KINDS = ("brand", "product", "category", "problem", "comparison", "buying", "industry",
                "competitor")


class AiPrompt(Base, ProjectScopedMixin):
    __tablename__ = "ai_prompts"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "text_hash", name="uq_ai_prompts_key"),
    )

    cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1")
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class AiPromptRun(Base, ProjectScopedMixin):
    __tablename__ = "ai_prompt_runs"
    __table_args__ = (Index("ix_ai_prompt_runs_prompt", "prompt_id", "created_at"),)

    prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_prompts.id", ondelete="CASCADE"), nullable=False
    )
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-US")
    ran_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parser: Mapped[str] = mapped_column(String(80), nullable=False, default="seo_core.geo.citations")
    parser_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.1.0")


class AiResponse(Base, ProjectScopedMixin):
    """Raw provider payload retained for audit (§F.4)."""

    __tablename__ = "ai_responses"

    prompt_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_prompt_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_key: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class AiCitation(Base, ProjectScopedMixin):
    __tablename__ = "ai_citations"

    prompt_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_prompt_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_mentioned: Mapped[bool] = mapped_column(nullable=False, default=False)
    brand_position: Mapped[int | None] = mapped_column(Integer)
    competitors_mentioned: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    cited_urls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    own_url_cited: Mapped[bool] = mapped_column(nullable=False, default=False)
    sentiment: Mapped[str] = mapped_column(String(12), nullable=False, default="neutral")


class AiVisibilityScore(Base, ProjectScopedMixin):
    __tablename__ = "ai_visibility_scores"
    __table_args__ = (
        UniqueConstraint("project_id", "cluster_id", "provider", "week",
                         name="uq_ai_visibility_key"),
    )

    cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    week: Mapped[datetime.date] = mapped_column(nullable=False)
    score: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    brand_mention_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    own_citation_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    prompts_run: Mapped[int] = mapped_column(Integer, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
