"""Event bus: transactional-outbox relay + idempotent consumers + DLQ
(A-TO-Z-PLAN.md §Phase 11 acceptance)."""

from __future__ import annotations

import uuid

import pytest

from db.models.events import OutboxEvent, ProcessedEvent
from db.models.identity import Tenant
from db.models.ops import DeadLetterEvent
from db.models.project import Project
from db.session import tenant_session
from events.bus import Event, dispatch_pending, register_consumer

CALLS: list[str] = []


def _ok_consumer(ev: Event, _s: object) -> None:
    CALLS.append(f"ok:{ev.type}:{ev.payload.get('n')}")


def _flaky_consumer(ev: Event, _s: object) -> None:
    raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _reset():
    CALLS.clear()
    register_consumer("test.ok", "t.demo", _ok_consumer)
    register_consumer("test.flaky", "t.flaky", _flaky_consumer)


@pytest.fixture
def project():
    t, p = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="assisted"))
    yield t, p
    with tenant_session(t, p) as s:
        for m in (DeadLetterEvent, ProcessedEvent, OutboxEvent, Project, Tenant):
            s.query(m).delete()


def test_relay_delivers_once_and_marks_published(project) -> None:
    t, p = project
    with tenant_session(t, p) as s:
        s.add(OutboxEvent(tenant_id=t, project_id=p, type="t.demo", version=1, payload={"n": 1}))
        s.add(OutboxEvent(tenant_id=t, project_id=p, type="t.demo", version=1, payload={"n": 2}))

    with tenant_session(t, p) as s:
        stats = dispatch_pending(s)
    assert stats["delivered"] == 2
    assert sorted(CALLS) == ["ok:t.demo:1", "ok:t.demo:2"]

    # second pass: nothing pending, no re-delivery
    CALLS.clear()
    with tenant_session(t, p) as s:
        stats2 = dispatch_pending(s)
        assert stats2["scanned"] == 0
        assert s.query(OutboxEvent).filter(OutboxEvent.published_at.isnot(None)).count() == 2
    assert CALLS == []


def test_failing_consumer_retries_then_dead_letters(project) -> None:
    t, p = project
    with tenant_session(t, p) as s:
        s.add(OutboxEvent(tenant_id=t, project_id=p, type="t.flaky", version=1, payload={"n": 9}))

    for _ in range(6):
        with tenant_session(t, p) as s:
            dispatch_pending(s)

    with tenant_session(t, p) as s:
        dl = s.query(DeadLetterEvent).one()
        assert dl.attempts >= 5 and "boom" in dl.last_error
        assert s.query(OutboxEvent).filter(OutboxEvent.published_at.isnot(None)).count() == 1
