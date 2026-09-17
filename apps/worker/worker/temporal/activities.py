"""Temporal activities for the autonomous SEO workflow (A-TO-Z-PLAN.md §Phase 11, ADR-0003).

Every side effect (DB access, event-bus draining, plan execution) lives here — the workflow
itself must stay deterministic and only call these. Each activity is a thin wrapper around an
existing worker job, so the business logic has one home (`worker.jobs.*`), not a Temporal-only
copy. Plain sync functions (the underlying jobs use blocking SQLAlchemy sessions) — the Temporal
Worker runs them on a thread-pool `activity_executor` (see `run_worker.py`)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from temporalio import activity


@dataclass
class DetectAndPlanInput:
    tenant_id: str
    project_id: str
    goal: str | None = None
    correlation_id: str | None = None


@dataclass
class DetectAndPlanResult:
    agent_run_id: str
    autonomous_plan_ids: list[str] = field(default_factory=list)
    awaiting_approval_plan_ids: list[str] = field(default_factory=list)


@activity.defn
def detect_and_plan(inp: DetectAndPlanInput) -> DetectAndPlanResult:
    """Drains the event bus (crawl.completed → issues → opportunities → plan.build, same as the
    one-shot `orchestrator.run_once`) and reports which plans are ready to auto-execute vs.
    waiting on a human — the workflow decides what to do with each, this just observes."""
    from db.models.safety import Plan
    from db.session import tenant_session
    from worker.jobs.orchestrator import run_once

    result = run_once(inp.tenant_id, inp.project_id, goal=inp.goal, trigger="temporal",
                      correlation_id=inp.correlation_id)

    tid, pid = uuid.UUID(inp.tenant_id), uuid.UUID(inp.project_id)
    with tenant_session(tid, pid) as s:
        autonomous = [
            str(p.id) for p in s.query(Plan)
            .filter(Plan.project_id == pid, Plan.state == "approved").all()
        ]
        waiting = [
            str(p.id) for p in s.query(Plan)
            .filter(Plan.project_id == pid, Plan.state == "awaiting_approval").all()
        ]
    return DetectAndPlanResult(agent_run_id=str(result["agent_run_id"]),
                               autonomous_plan_ids=autonomous, awaiting_approval_plan_ids=waiting)


@dataclass
class ExecutePlanInput:
    tenant_id: str
    project_id: str
    plan_id: str
    repo_path: str = "."
    correlation_id: str | None = None


@dataclass
class ExecutePlanResult:
    plan_id: str
    results: list[dict[str, object]] = field(default_factory=list)


@activity.defn
def execute_approved_plan(inp: ExecutePlanInput) -> ExecutePlanResult:
    """Runs `plan.execute` — approval/guardrail checks happen again here (defense in depth); an
    autonomous plan's own steps still carry `permission='auto'` from the planner, and a
    human-approved plan needs its `Approval` row already recorded by the API before this fires."""
    from worker.jobs.planning import execute

    out = execute(inp.tenant_id, inp.project_id, inp.plan_id, repo_path=inp.repo_path,
                  correlation_id=inp.correlation_id)
    results = out.get("results", [])
    return ExecutePlanResult(plan_id=inp.plan_id,
                             results=list(results) if isinstance(results, list) else [])
