"""Knowledge graph (A-TO-Z-PLAN.md §G, ADR-0002) — PostgreSQL, no Neo4j.

`kg_nodes` / `kg_edges` are the typed graph. Edges are evidence-backed via `evidence_links`
(subject_type='kg_edge'). `search_tsv` powers lexical retrieval; the vector half references the
dedicated `embeddings` table (§Z) — only node types in §Z get embedded."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin, TenantMixin

NODE_TYPES = (
    "Website", "Page", "Keyword", "Topic", "Entity", "Query", "SERP", "Competitor", "Backlink",
    "InternalLink", "Schema", "Issue", "Opportunity", "Change", "Experiment", "Metric", "Content",
    "Author", "Product", "Category", "Location", "AIPrompt", "AIResponse", "Citation",
)
EDGE_RELATIONS = (
    "ranks_for", "covers", "mentions", "links_to", "appears_in", "has_issue",
    "creates", "produces", "affects", "verified_by", "cites",
)


class KgNode(Base, ProjectScopedMixin):
    __tablename__ = "kg_nodes"
    __table_args__ = (
        UniqueConstraint("project_id", "type", "ref_id", name="uq_kg_nodes_project_type_ref"),
        Index("ix_kg_nodes_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_kg_nodes_label_trgm", "label", postgresql_using="gin",
              postgresql_ops={"label": "gin_trgm_ops"}),
        Index("ix_kg_nodes_type", "project_id", "type"),
    )

    type: Mapped[str] = mapped_column(String(24), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(80), nullable=False)  # natural key: e.g. url_hash, keyword id
    label: Mapped[str] = mapped_column(Text, nullable=False)
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    embedding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class KgEdge(Base, ProjectScopedMixin):
    __tablename__ = "kg_edges"
    __table_args__ = (
        UniqueConstraint("src", "dst", "relation", name="uq_kg_edges_src_dst_rel"),
        Index("ix_kg_edges_src", "src", "relation"),
        Index("ix_kg_edges_dst", "dst", "relation"),
    )

    src: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False
    )
    dst: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(20), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False, default=1.0)
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class Embedding(Base, ProjectScopedMixin):
    """§Z — dedicated table, not a column on every entity. Model + version + content_hash so
    stale detection and re-embed are cheap."""

    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", "model", "model_version",
                         name="uq_embeddings_owner_model"),
        Index("ix_embeddings_stale", "project_id", "stale"),
    )

    owner_type: Mapped[str] = mapped_column(String(24), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    dim: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[list[float] | None] = mapped_column(JSONB)  # pgvector column swapped in when EMBEDDING role is live
    stale: Mapped[bool] = mapped_column(nullable=False, default=False)


class EmbeddingJob(Base, TenantMixin):
    __tablename__ = "embedding_jobs"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    owner_type: Mapped[str] = mapped_column(String(24), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
