"""Minimal orchestrator loop (A-TO-Z-PLAN.md §Phase 11, §J).

An `agent_runs`-backed driver for the OBSERVE→…→LEARN loop under **assisted** mode. This is NOT
the production Orchestrator — that is a Temporal workflow (ADR-0003) that survives multi-day
waits and approval signals. This version:
  1. opens an agent_run (correlation id threads everything),
  2. drains the event bus (relay) so the pipeline advances,
  3. records the state it reached and stops at the approval gate.
State is a DB row, so a crash mid-run is recoverable (re-invoke → resume from `agent_runs.state`).
"""

from __future__ import annotations

import datetime as dt
import uuid

import structlog

from db.models.opportunity import Opportunity
from db.models.ops import AgentRun
from db.models.safety import Plan
from db.session import tenant_session

log = structlog.get_logger("job.orchestrator")
UTC = dt.UTC


def run_once(tenant_id: str, project_id: str, *, goal: str | None = None,
             trigger: str = "manual", correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    corr = correlation_id or str(uuid.uuid4())
    now = dt.datetime.now(UTC)

    with tenant_session(tid, pid) as s:
        run = AgentRun(tenant_id=tid, project_id=pid, goal=goal, trigger=trigger,
                       state="detecting", correlation_id=corr, started_at=now, stats={})
        s.add(run)
        s.flush()
        run_id = run.id

    # drain the bus: crawl.completed → analyze → issues → opportunities → plan.build
    import worker.pipeline  # noqa: F401  (registers consumers)
    from events.bus import dispatch_pending

    passes = 0
    with tenant_session(tid, pid) as s:
        for _ in range(5):  # a few passes so chained events (issue→opportunity→plan) settle
            stats = dispatch_pending(s)
            passes += 1
            if stats["scanned"] == 0:
                break

    with tenant_session(tid, pid) as s:
        awaiting = s.query(Plan).filter(
            Plan.project_id == pid, Plan.state == "awaiting_approval"
        ).count()
        p0p1 = s.query(Opportunity).filter(
            Opportunity.project_id == pid,
            Opportunity.priority.in_(("P0", "P1")),
            Opportunity.status.in_(("detected", "planned", "awaiting_approval")),
        ).count()
        final = s.get(AgentRun, run_id)
        if final is None:
            raise RuntimeError("agent_run vanished")
        final.state = "awaiting_approval" if awaiting else "measuring"
        final.finished_at = dt.datetime.now(UTC)
        final.stats = {"relay_passes": passes, "plans_awaiting_approval": awaiting,
                     "priority_opportunities": p0p1}
        s.add(final)
        result_state = final.state

    log.info("orchestrator.run_once", run_id=str(run_id), state=result_state,
             awaiting_approval=awaiting)
    return {"agent_run_id": str(run_id), "state": result_state,
            "plans_awaiting_approval": awaiting, "priority_opportunities": p0p1}
