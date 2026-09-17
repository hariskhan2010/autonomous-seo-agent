"""Agent-runtime scaffolding (A-TO-Z-PLAN.md §F, §X, §Y).

Phase 1 lays the tables; the planner/executor/router fill them from Phase 8/11.
- resource_locks : project/resource leases (§X) — two runs can't hold conflicting write leases.
- job_runs       : idempotency-key ledger (§X) — redelivered job returns the prior result.
- prompt_templates / agent_versions : versioning for reproducibility (§Y). Identity-global config.
- model_registry : per-tenant role->model overrides (defaults live in config/model_registry.yaml).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, TenantMixin, TimestampMixin, UUIDPKMixin


class ResourceLock(Base, TenantMixin):
    __tablename__ = "resource_locks"
    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", name="uq_resource_locks_resource"),
    )

    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)  # project / page / change ...
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    holder_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="write")  # write / read
    acquired_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobRun(Base, TenantMixin):
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_job_runs_idempotency_key"),
    )

    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")  # running/succeeded/failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class PromptTemplate(Base, UUIDPKMixin, TimestampMixin):
    """Identity-global. Versioned + content-hashed (§Y)."""

    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompt_templates_name_version"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class AgentVersion(Base, UUIDPKMixin, TimestampMixin):
    """Identity-global. Semver per agent definition (§Y)."""

    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent", "version", name="uq_agent_versions_agent_version"),)

    agent: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    model_role: Mapped[str] = mapped_column(String(16), nullable=False)  # STRATEGY/WORKER/FAST/JUDGE
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class ModelRegistryOverride(Base, TenantMixin):
    """Per-tenant role->model override. Absent => use config/model_registry.yaml default."""

    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("tenant_id", "role", name="uq_model_registry_tenant_role"),)

    role: Mapped[str] = mapped_column(String(16), nullable=False)  # STRATEGY/WORKER/FAST/JUDGE/EMBEDDING
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    fallbacks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
