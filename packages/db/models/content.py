"""Content intelligence models (A-TO-Z-PLAN.md §Phase 5, §F)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

CONTENT_TYPES = ("article", "product", "category", "collection", "landing", "home", "doc", "other")


class Topic(Base, ProjectScopedMixin):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_topics_project_slug"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    pillar_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="cluster")  # pillar/cluster/supporting


class Entity(Base, ProjectScopedMixin):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("project_id", "normalized", name="uq_entities_project_norm"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="thing")
    mentions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ContentItem(Base, ProjectScopedMixin):
    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("project_id", "url_hash", name="uq_content_items_project_url"),
        Index("ix_content_items_type", "project_id", "content_type"),
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    title: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at_seen: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    author: Mapped[str | None] = mapped_column(String(200))
    canonical_target: Mapped[str | None] = mapped_column(Text)
    primary_keyword_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")  # thin/outdated/cannibalized/orphan
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class ContentScore(Base, ProjectScopedMixin):
    __tablename__ = "content_scores"
    __table_args__ = (Index("ix_content_scores_item", "content_item_id", "created_at"),)

    content_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    scorer: Mapped[str] = mapped_column(String(16), nullable=False, default="rule")  # rule / judge
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    verdict: Mapped[str] = mapped_column(String(12), nullable=False)  # PASS / REVISE / FAIL
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
