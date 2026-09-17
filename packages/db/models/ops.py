"""Event-bus + scheduler ops tables (A-TO-Z-PLAN.md §Phase 11, §F.3, §45–46)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, TenantMixin


class DeadLetterEvent(Base, TenantMixin):
    __tablename__ = "dead_letter_events"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    consumer: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, nullable=False)
    replayed: Mapped[bool] = mapped_column(nullable=False, default=False)


class Schedule(Base, TenantMixin):
    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "name", name="uq_schedules_key"),
        Index("ix_schedules_due", "enabled", "next_run_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)  # daily/weekly/monthly
    task: Mapped[str] = mapped_column(String(80), nullable=False)     # celery task name
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_run_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRun(Base, TenantMixin):
    """The autonomous loop's run row (A-TO-Z-PLAN.md §J). Orchestrator (Temporal, when available)
    or the event-driven pipeline advances `state`."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_state", "tenant_id", "state"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    goal: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(24), nullable=False, default="event")  # event/schedule/manual
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="observing")
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
