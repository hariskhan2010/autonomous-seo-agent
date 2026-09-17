"""Safety spine models (A-TO-Z-PLAN.md §Phase 8, §K, §Y).

plans/plan_steps (structured, DAG) → approvals → changes/change_versions (pre_state_hash,
side_effect_key) → verifications → rollbacks → incidents. `agent_decisions` is the
reproducibility record for every material autonomous decision (§Y)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
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

PLAN_STATES = ("draft", "awaiting_approval", "approved", "rejected", "executing", "done", "failed")
CHANGE_STATES = ("planned", "previewed", "backed_up", "applied", "verified", "failed", "rolled_back")
APPROVAL_DECISIONS = ("approved", "rejected", "auto_approved")


class Plan(Base, ProjectScopedMixin):
    __tablename__ = "plans"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    root_cause: Mapped[str | None] = mapped_column(Text)
    chosen_solution: Mapped[str | None] = mapped_column(Text)
    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=True)
    max_action_class: Mapped[str] = mapped_column(String(28), nullable=False, default="LOW_RISK_WRITE")
    agent_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class PlanStep(Base, ProjectScopedMixin):
    """Structured — no free-form plans (A-TO-Z-PLAN.md §Phase 8)."""

    __tablename__ = "plan_steps"
    __table_args__ = (UniqueConstraint("plan_id", "ordinal", name="uq_plan_steps_plan_ordinal"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.1.0")
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    preconditions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    expected_output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    action_class: Mapped[str] = mapped_column(String(28), nullable=False)
    permission: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    verification: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    rollback: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    depends_on: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)


class Approval(Base, ProjectScopedMixin):
    __tablename__ = "approvals"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # null = system (auto)
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Change(Base, ProjectScopedMixin):
    __tablename__ = "changes"
    __table_args__ = (
        UniqueConstraint("side_effect_key", name="uq_changes_side_effect_key"),
        Index("ix_changes_plan", "plan_id"),
    )

    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    plan_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    adapter: Mapped[str] = mapped_column(String(24), nullable=False)  # git_pr / wordpress / ...
    action_class: Mapped[str] = mapped_column(String(28), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    target: Mapped[str] = mapped_column(Text, nullable=False)
    pre_state_hash: Mapped[str | None] = mapped_column(String(64))
    rollback_strategy: Mapped[str] = mapped_column(String(24), nullable=False)  # native / version_restore / compensating / manual / none
    backup_ref: Mapped[str | None] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(Text)  # PR url, revision id
    side_effect_key: Mapped[str] = mapped_column(String(80), nullable=False)
    applied_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class ChangeVersion(Base, ProjectScopedMixin):
    __tablename__ = "change_versions"

    change_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("changes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class Verification(Base, ProjectScopedMixin):
    __tablename__ = "verifications"

    change_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("changes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # technical (immediate)
    passed: Mapped[bool] = mapped_column(nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    checked_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Rollback(Base, ProjectScopedMixin):
    __tablename__ = "rollbacks"

    change_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("changes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy: Mapped[str] = mapped_column(String(24), nullable=False)
    succeeded: Mapped[bool] = mapped_column(nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    executed_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Incident(Base, ProjectScopedMixin):
    __tablename__ = "incidents"

    change_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="high")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class AgentDecision(Base, ProjectScopedMixin):
    """Reproducibility record (A-TO-Z-PLAN.md §Y)."""

    __tablename__ = "agent_decisions"
    __table_args__ = (Index("ix_agent_decisions_kind", "project_id", "kind"),)

    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # plan_chosen / solution_selected / ...
    agent: Mapped[str] = mapped_column(String(60), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_id: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    model_role: Mapped[str | None] = mapped_column(String(16))
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(60))
    tool_versions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    evidence_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    rationale: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
