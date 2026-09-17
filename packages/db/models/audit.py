"""Audit log (A-TO-Z-PLAN.md §N, §52) — every user and agent action. Append-only.
`agent_decisions` (the reproducibility record, §Y) arrives with the planner in Phase 8."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, TenantMixin


class AuditLog(Base, TenantMixin):
    __tablename__ = "audit_logs"

    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user / agent / system
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    ip: Mapped[str | None] = mapped_column(String(45))
    note: Mapped[str | None] = mapped_column(Text)
