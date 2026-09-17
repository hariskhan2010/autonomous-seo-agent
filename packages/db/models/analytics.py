"""Analytics + experiments + learning models (A-TO-Z-PLAN.md §Phase 9, §21, §34–35).

`experiments` carries the methodology (baseline/treatment windows, control, metric defs,
confounders) so no result can claim causal impact without it (§Phase 9 rule)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

METRIC_NAMES = (
    "clicks", "impressions", "ctr", "position", "organic_sessions", "conversions",
    "revenue", "indexed_pages", "crawl_errors",
)
EXPERIMENT_STATES = ("designed", "running", "measuring", "concluded")
EXPERIMENT_VERDICTS = ("success", "neutral", "regression", "inconclusive")


class MetricSnapshot(Base, ProjectScopedMixin):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "metric", "scope", "scope_ref", "date",
                         name="uq_metric_snapshots_key"),
        Index("ix_metric_snapshots_metric_date", "project_id", "metric", "date"),
    )

    metric: Mapped[str] = mapped_column(String(24), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="site")  # site / page / query / cluster
    scope_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="*")
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="gsc")


class Anomaly(Base, ProjectScopedMixin):
    __tablename__ = "anomalies"

    metric: Mapped[str] = mapped_column(String(24), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="site")
    scope_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="*")
    detected_on: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # drop / spike
    magnitude_pct: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    baseline: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    observed: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    z_score: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    investigation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class Experiment(Base, ProjectScopedMixin):
    __tablename__ = "experiments"

    experiment_type: Mapped[str] = mapped_column(String(24), nullable=False)  # title/meta/internal_link/...
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    change_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    primary_metric: Mapped[str] = mapped_column(String(24), nullable=False)
    metric_definitions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    baseline_start: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    baseline_end: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    treatment_start: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    measurement_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=28)
    control: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")  # {kind, refs}
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="designed")
    verdict: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    methodology: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    confounders: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    concluded_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class Learning(Base, ProjectScopedMixin):
    __tablename__ = "learnings"

    source_type: Mapped[str] = mapped_column(String(24), nullable=False)  # experiment / observation
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    opportunity_type: Mapped[str | None] = mapped_column(String(40), index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    weight_delta: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0.0)
    methodology_note: Mapped[str | None] = mapped_column(Text)


class OpportunityWeight(Base, ProjectScopedMixin):
    """The closed-loop weights the opportunity engine reads (A-TO-Z-PLAN.md §35)."""

    __tablename__ = "opportunity_weights"
    __table_args__ = (
        UniqueConstraint("project_id", "opportunity_type", name="uq_opportunity_weights_type"),
    )

    opportunity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    multiplier: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False, default=1.0)
    updated_from_learning: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class MemoryEntry(Base, ProjectScopedMixin):
    """Project + historical memory (A-TO-Z-PLAN.md §33). Short-term = run scratchpad (not here)."""

    __tablename__ = "memory_entries"
    __table_args__ = (Index("ix_memory_entries_kind", "project_id", "kind"),)

    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # project / historical
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    recorded_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
