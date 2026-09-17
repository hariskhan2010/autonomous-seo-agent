"""`POST /v1/plans/{id}/approve` also best-effort signals a running Temporal workflow
(ADR-0003) after the DB commit — verified here by monkeypatching `signal_approval` to record its
call; a real Temporal server isn't needed to prove the wiring fires with the right args, in the
right order, and never breaks the approval write itself if signalling fails."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.main import app
from fastapi.testclient import TestClient

from db.models.identity import Tenant
from db.models.opportunity import Opportunity
from db.models.project import Project
from db.models.safety import Approval, Plan
from db.session import tenant_session

client = TestClient(app)


def _headers(tenant: uuid.UUID, user: uuid.UUID, role: str = "operator") -> dict[str, str]:
    return {"x-dev-tenant": str(tenant), "x-dev-user": str(user), "x-dev-role": role}


@pytest.fixture
def plan():
    t, p, oid, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="assisted"))
        now = dt.datetime.now(dt.UTC)
        s.add(Opportunity(
            id=oid, tenant_id=t, project_id=p, type="fix_canonical",
            normalized_key=f"k-{oid.hex[:8]}", title="Canonical points elsewhere",
            url="https://x.com/a", priority="P1", status="planned",
            detector="technical_engine", first_seen=now, last_seen=now,
        ))
        s.flush()
        s.add(Plan(
            id=pid, tenant_id=t, project_id=p, opportunity_id=oid, state="awaiting_approval",
            root_cause="fix_canonical", chosen_solution="self-canonical", requires_approval=True,
            max_action_class="LOW_RISK_WRITE",
        ))
    yield t, p, pid
    with tenant_session(t, p) as s:
        for m in (Approval, Plan, Opportunity, Project, Tenant):
            s.query(m).delete()


def test_approve_records_approval_and_updates_plan_state(plan: tuple) -> None:
    t, p, pid = plan
    r = client.post(
        f"/v1/plans/{pid}/approve", json={"decision": "approved", "note": "looks safe"},
        headers=_headers(t, uuid.uuid4()),
    )
    assert r.status_code == 201, r.text
    with tenant_session(t, p) as s:
        updated = s.get(Plan, pid)
        assert updated is not None and updated.state == "approved"
        assert s.query(Approval).filter(Approval.plan_id == pid).one().decision == "approved"


def test_approve_signals_temporal_when_configured(
    plan: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, p, pid = plan
    calls: list[dict[str, object]] = []

    async def _fake_signal(tenant_id: str, project_id: str, *, plan_id: str, decision: str) -> None:
        calls.append({"tenant_id": tenant_id, "project_id": project_id, "plan_id": plan_id,
                      "decision": decision})

    import worker.temporal.client as temporal_client_module

    from common.settings import settings

    monkeypatch.setattr(settings, "temporal_address", "localhost:7233")
    monkeypatch.setattr(temporal_client_module, "signal_approval", _fake_signal)

    r = client.post(
        f"/v1/plans/{pid}/approve", json={"decision": "approved", "note": "ok"},
        headers=_headers(t, uuid.uuid4()),
    )
    assert r.status_code == 201, r.text
    assert calls == [{"tenant_id": str(t), "project_id": str(p), "plan_id": str(pid),
                      "decision": "approved"}]


def test_approve_does_not_signal_temporal_when_unconfigured(
    plan: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, p, pid = plan
    calls: list[object] = []

    async def _fake_signal(*a: object, **kw: object) -> None:
        calls.append((a, kw))

    import worker.temporal.client as temporal_client_module

    from common.settings import settings

    monkeypatch.setattr(settings, "temporal_address", "")
    monkeypatch.setattr(temporal_client_module, "signal_approval", _fake_signal)

    r = client.post(
        f"/v1/plans/{pid}/approve", json={"decision": "approved", "note": "ok"},
        headers=_headers(t, uuid.uuid4()),
    )
    assert r.status_code == 201, r.text
    assert calls == []


def test_approve_succeeds_even_if_temporal_signal_fails(
    plan: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, p, pid = plan

    async def _boom(*a: object, **kw: object) -> None:
        raise RuntimeError("no workflow running for this tenant/project")

    import worker.temporal.client as temporal_client_module

    from common.settings import settings

    monkeypatch.setattr(settings, "temporal_address", "localhost:7233")
    monkeypatch.setattr(temporal_client_module, "signal_approval", _boom)

    r = client.post(
        f"/v1/plans/{pid}/approve", json={"decision": "approved", "note": "ok"},
        headers=_headers(t, uuid.uuid4()),
    )
    assert r.status_code == 201, r.text  # the Approval write still succeeds
    with tenant_session(t, p) as s:
        assert s.get(Plan, pid).state == "approved"
