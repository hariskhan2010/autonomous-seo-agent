"""Celery beat schedule (A-TO-Z-PLAN.md §Phase 11 — "Deferred: Celery beat wiring").

`scheduler.tick` (due `schedules` rows -> enqueue) and `events.relay` (outbox -> consumers) are
both per-(tenant, project) tasks: every DB touch goes through `tenant_session`, and the runtime
role is NOBYPASSRLS, so there is no safe way for beat to discover "all projects" on its own.
The targets are therefore explicit configuration (`settings.beat_targets`), and this module is
a pure function from that config to a Celery `beat_schedule` dict — no I/O, unit-testable.

Each entry carries `expires` = its own interval, so if workers fall behind, stale ticks are
dropped instead of piling up (both tasks are idempotent; the next tick catches up)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class BeatTarget:
    tenant_id: str
    project_id: str


def parse_beat_targets(raw: str) -> list[BeatTarget]:
    """`"t1:p1, t2:p2"` -> targets. Raises `ValueError` on a malformed pair — a typo here would
    otherwise silently schedule nothing for that project, so fail loudly at worker/beat start.
    Duplicate pairs collapse to one."""
    out: list[BeatTarget] = []
    seen: set[BeatTarget] = set()
    for chunk in raw.split(","):
        pair = chunk.strip()
        if not pair:
            continue
        tenant, sep, project = pair.partition(":")
        if not sep:
            raise ValueError(f"beat target {pair!r} is not 'tenant_uuid:project_uuid'")
        try:
            target = BeatTarget(str(uuid.UUID(tenant.strip())), str(uuid.UUID(project.strip())))
        except ValueError as exc:
            raise ValueError(f"beat target {pair!r} has a non-UUID part") from exc
        if target not in seen:
            seen.add(target)
            out.append(target)
    return out


def build_beat_schedule(
    targets: list[BeatTarget], *, scheduler_tick_seconds: float, events_relay_seconds: float,
) -> dict[str, dict[str, object]]:
    """One `scheduler.tick` + one `events.relay` entry per target."""
    if scheduler_tick_seconds <= 0 or events_relay_seconds <= 0:
        raise ValueError("beat intervals must be positive")
    schedule: dict[str, dict[str, object]] = {}
    for t in targets:
        kwargs = {"tenant_id": t.tenant_id, "project_id": t.project_id}
        schedule[f"scheduler.tick:{t.project_id}"] = {
            "task": "scheduler.tick",
            "schedule": scheduler_tick_seconds,
            "kwargs": dict(kwargs),
            "options": {"expires": scheduler_tick_seconds},
        }
        schedule[f"events.relay:{t.project_id}"] = {
            "task": "events.relay",
            "schedule": events_relay_seconds,
            "kwargs": dict(kwargs),
            "options": {"expires": events_relay_seconds},
        }
    return schedule
