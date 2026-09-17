"""Event bus — transactional-outbox relay + idempotent consumers + DLQ
(A-TO-Z-PLAN.md §F.3, §Phase 11, ADR-0007).

The DB is the source of truth. `dispatch_pending` polls unpublished `outbox_events`, runs every
registered consumer, records `processed_events` (dedupe), and dead-letters after `max_attempts`.
Consumers must be idempotent — a redelivered event is a no-op."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.events import OutboxEvent, ProcessedEvent
from db.models.ops import DeadLetterEvent

log = structlog.get_logger("events.bus")

MAX_ATTEMPTS = 5


@dataclass
class Event:
    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID | None
    type: str
    version: int
    correlation_id: str | None
    payload: dict[str, object]


Consumer = Callable[[Event, Session], None]
_REGISTRY: dict[str, list[tuple[str, Consumer]]] = {}


def register_consumer(name: str, event_type: str, fn: Consumer) -> None:
    _REGISTRY.setdefault(event_type, [])
    if name not in {n for n, _ in _REGISTRY[event_type]}:
        _REGISTRY[event_type].append((name, fn))


def consumer(name: str, event_type: str) -> Callable[[Consumer], Consumer]:
    def deco(fn: Consumer) -> Consumer:
        register_consumer(name, event_type, fn)
        return fn
    return deco


def _to_event(row: OutboxEvent) -> Event:
    return Event(id=row.event_id, tenant_id=row.tenant_id, project_id=row.project_id,
                 type=row.type, version=row.version, correlation_id=row.correlation_id,
                 payload=dict(row.payload or {}))


def dispatch_pending(session: Session, *, limit: int = 100) -> dict[str, int]:
    """One relay pass. Call from `events.relay` (worker beat) or a test."""
    import datetime as dt

    rows = session.execute(
        select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at).limit(limit)
    ).scalars().all()

    delivered = failed = dead = 0
    for row in rows:
        ev = _to_event(row)
        consumers = _REGISTRY.get(ev.type, [])
        all_ok = True
        for name, fn in consumers:
            already = session.execute(
                select(ProcessedEvent).where(
                    ProcessedEvent.event_id == ev.id, ProcessedEvent.consumer == name
                )
            ).scalar_one_or_none()
            if already is not None:
                continue
            try:
                fn(ev, session)
                session.add(ProcessedEvent(tenant_id=ev.tenant_id, event_id=ev.id,
                                           consumer=name, outcome="ok"))
                delivered += 1
            except Exception as exc:  # noqa: BLE001
                all_ok = False
                failed += 1
                row.attempts = (row.attempts or 0) + 1
                row.last_error = str(exc)[:2000]
                log.warning("event.consumer_failed", event_type=ev.type, consumer=name,
                            attempts=row.attempts, error=str(exc)[:200])
                if row.attempts >= MAX_ATTEMPTS:
                    session.add(DeadLetterEvent(
                        tenant_id=ev.tenant_id, event_id=ev.id, consumer=name, type=ev.type,
                        payload=ev.payload, attempts=row.attempts, last_error=str(exc)[:2000],
                    ))
                    session.add(ProcessedEvent(tenant_id=ev.tenant_id, event_id=ev.id,
                                               consumer=name, outcome="dead_letter"))
                    dead += 1
        if all_ok or (row.attempts or 0) >= MAX_ATTEMPTS:
            row.published_at = dt.datetime.now(dt.UTC)
        session.add(row)

    return {"scanned": len(rows), "delivered": delivered, "failed": failed, "dead_lettered": dead}
