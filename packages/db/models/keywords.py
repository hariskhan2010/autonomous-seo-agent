"""Keyword + intent + clustering models (A-TO-Z-PLAN.md §Phase 4, §F).

`keyword_page_map` ties a keyword to the page we rank (or want to rank) it with — the input to
cannibalization detection. `search_intents` is multi-label (mixed intent) with per-label
confidence."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

INTENT_CLASSES = (
    "informational", "navigational", "commercial", "transactional", "local",
    "visual", "video", "news", "question", "comparison", "how_to", "definitional",
)


class Keyword(Base, ProjectScopedMixin):
    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized", name="uq_keywords_project_norm"),
        Index("ix_keywords_tenant_project", "tenant_id", "project_id"),
    )

    term: Mapped[str] = mapped_column(Text, nullable=False)
    normalized: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="seed")  # seed/related/paa/gsc/competitor
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-US")
    volume: Mapped[int | None] = mapped_column(Integer)
    volume_estimated: Mapped[bool] = mapped_column(nullable=False, default=False)
    difficulty: Mapped[float | None] = mapped_column(Numeric(5, 2))
    difficulty_estimated: Mapped[bool] = mapped_column(nullable=False, default=False)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("keyword_clusters.id", ondelete="SET NULL"), index=True
    )
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class KeywordCluster(Base, ProjectScopedMixin):
    __tablename__ = "keyword_clusters"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_keyword_clusters_project_slug"),)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False, default="token_jaccard")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    volume_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    primary_intent: Mapped[str | None] = mapped_column(String(20))
    intents: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")


class SearchIntent(Base, ProjectScopedMixin):
    """One row per (keyword, label). A keyword with mixed intent has several rows."""

    __tablename__ = "search_intents"
    __table_args__ = (
        UniqueConstraint("keyword_id", "label", name="uq_search_intents_keyword_label"),
    )

    keyword_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="rule")  # rule / model


class KeywordPageMap(Base, ProjectScopedMixin):
    __tablename__ = "keyword_page_map"
    __table_args__ = (
        UniqueConstraint("keyword_id", "url_hash", name="uq_keyword_page_map_kw_url"),
        Index("ix_keyword_page_map_kw", "keyword_id"),
    )

    keyword_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    relation: Mapped[str] = mapped_column(String(16), nullable=False, default="ranks")  # ranks / target / mention
    position: Mapped[float | None] = mapped_column(Numeric(5, 2))
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="serp")  # serp / gsc
