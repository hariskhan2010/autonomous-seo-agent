"""Transactional outbox + consumer dedupe (A-TO-Z-PLAN.md §F.3, ADR-0007).

Domain writes and the `OutboxEvent` insert happen in the SAME transaction. A relay publishes
unpublished rows to the bus. Consumers record `ProcessedEvent` and no-op on replay."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, TenantMixin


class OutboxEvent(Base, TenantMixin):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_unpublished", "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessedEvent(Base, TenantMixin):
    __tablename__ = "processed_events"
    __table_args__ = (
        UniqueConstraint("event_id", "consumer", name="uq_processed_events_event_consumer"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    consumer: Mapped[str] = mapped_column(String(120), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")  # ok/skipped/dead_letter
