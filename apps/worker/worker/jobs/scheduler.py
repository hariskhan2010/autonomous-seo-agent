"""Scheduler tick (A-TO-Z-PLAN.md §Phase 11, §45).

Reads due `schedules`, enqueues each task (Celery in prod; returns the plan here), bumps
`next_run_at`. A time-based trigger only — it holds no workflow state (§AA)."""

from __future__ import annotations

import datetime as dt
import uuid

import structlog

from db.models.ops import Schedule
from db.session import tenant_session

log = structlog.get_logger("job.scheduler")
UTC = dt.UTC

_CADENCE = {"daily": dt.timedelta(days=1), "weekly": dt.timedelta(days=7),
            "monthly": dt.timedelta(days=30), "hourly": dt.timedelta(hours=1)}


def tick(tenant_id: str, project_id: str, *, now: dt.datetime | None = None,
         enqueue: object = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    now = now or dt.datetime.now(UTC)
    fired: list[dict[str, object]] = []
    with tenant_session(tid, pid) as s:
        due = s.query(Schedule).filter(
            Schedule.tenant_id == tid, Schedule.project_id == pid,
            Schedule.enabled.is_(True), Schedule.next_run_at <= now,
        ).all()
        for sched in due:
            payload: dict[str, object] = {"task": sched.task, "args": dict(sched.args or {}), "schedule": sched.name}
            if callable(enqueue):
                enqueue(sched.task, {"tenant_id": tenant_id, "project_id": project_id,
                                     **(sched.args or {})})
            sched.last_run_at = now
            sched.next_run_at = now + _CADENCE.get(sched.cadence, dt.timedelta(days=1))
            s.add(sched)
            fired.append(payload)
    log.info("scheduler.tick", fired=len(fired))
    return {"fired": len(fired), "tasks": [f["task"] for f in fired]}
