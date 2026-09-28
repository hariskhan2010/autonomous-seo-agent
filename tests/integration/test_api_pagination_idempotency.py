"""Cursor pagination + `Idempotency-Key` over HTTP against real Postgres (Phase 12 deferral):
keyset paging walks every row exactly once even with tied sort keys, and a retried POST with the
same key replays instead of writing twice (`job_runs` ledger, under RLS)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.main import app
from fastapi.testclient import TestClient

from db.models.identity import Tenant
from db.models.opportunity import Opportunity
from db.models.project import Project, Website
from db.models.runtime import JobRun
from db.models.safety import Approval, Plan
from db.session import tenant_session

client = TestClient(app)
UTC = dt.UTC


def _headers(tenant: uuid.UUID, user: uuid.UUID, role: str = "owner") -> dict[str, str]:
    return {"x-dev-tenant": str(tenant), "x-dev-user": str(user), "x-dev-role": role}


@pytest.fixture
def project():
    t, p = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="assisted"))
    yield t, p
    with tenant_session(t, p) as s:
        for m in (Approval, Plan, Opportunity):
            s.query(m).delete()
    with tenant_session(t) as s:
        s.query(JobRun).delete()
        s.query(Website).delete()
        s.query(Project).delete()
        s.query(Tenant).delete()


def _seed_opportunities(t: uuid.UUID, p: uuid.UUID, scores: list[float]) -> set[str]:
    now = dt.datetime.now(UTC)
    ids: set[str] = set()
    with tenant_session(t, p) as s:
        for i, score in enumerate(scores):
            o = Opportunity(tenant_id=t, project_id=p, type="fix_technical_issue",
                            normalized_key=f"k{i}", title=f"o{i}", detector="technical",
                            first_seen=now, last_seen=now, score=score)
            s.add(o)
            s.flush()
            ids.add(str(o.id))
    return ids


def test_keyset_pages_cover_every_row_once_with_tied_scores(
    project: tuple[uuid.UUID, uuid.UUID],
) -> None:
    t, p = project
    # Deliberate ties on the sort key — the `id` tiebreak is what keeps pages disjoint.
    expected = _seed_opportunities(t, p, [5.0, 5.0, 5.0, 3.0, 3.0, 1.0, 1.0])
    h = _headers(t, uuid.uuid4())

    legacy = client.get("/v1/opportunities", params={"project_id": str(p)}, headers=h)
    assert legacy.status_code == 200
    assert {o["id"] for o in legacy.json()} == expected
    assert "x-next-cursor" not in legacy.headers

    seen: list[str] = []
    scores: list[float] = []
    params: dict[str, str] = {"project_id": str(p), "limit": "3"}
    for _ in range(10):
        r = client.get("/v1/opportunities", params=params, headers=h)
        assert r.status_code == 200, r.text
        seen += [o["id"] for o in r.json()]
        scores += [o["score"] for o in r.json()]
        nxt = r.headers.get("x-next-cursor")
        if nxt is None:
            break
        params["cursor"] = nxt
    assert len(seen) == len(expected)
    assert set(seen) == expected
    assert scores == sorted(scores, reverse=True)


def test_approve_with_same_key_replays_and_writes_one_approval(
    project: tuple[uuid.UUID, uuid.UUID],
) -> None:
    t, p = project
    (oid,) = _seed_opportunities(t, p, [2.0])
    with tenant_session(t, p) as s:
        plan = Plan(tenant_id=t, project_id=p, opportunity_id=uuid.UUID(oid),
                    state="awaiting_approval", requires_approval=True,
                    max_action_class="LOW_RISK_WRITE")
        s.add(plan)
        s.flush()
        pid = plan.id

    h = {**_headers(t, uuid.uuid4(), role="operator"), "Idempotency-Key": "approve-once"}
    body = {"decision": "approved", "note": "ok"}
    first = client.post(f"/v1/plans/{pid}/approve", json=body, headers=h)
    assert first.status_code == 201, first.text
    assert "idempotent-replayed" not in first.headers

    retry = client.post(f"/v1/plans/{pid}/approve", json=body, headers=h)
    assert retry.status_code == 201
    assert retry.json() == first.json()
    assert retry.headers["idempotent-replayed"] == "true"

    changed = client.post(f"/v1/plans/{pid}/approve",
                          json={"decision": "rejected", "note": "no"}, headers=h)
    assert changed.status_code == 422

    with tenant_session(t, p) as s:
        assert s.query(Approval).filter(Approval.plan_id == pid).count() == 1


def test_failed_request_does_not_burn_the_key(project: tuple[uuid.UUID, uuid.UUID]) -> None:
    t, _p = project
    h = {**_headers(t, uuid.uuid4()), "Idempotency-Key": "create-w"}
    missing_project = {"project_id": str(uuid.uuid4()), "origin": "https://example.com"}
    assert client.post("/v1/websites", json=missing_project, headers=h).status_code == 404
    with tenant_session(t) as s:
        assert s.query(JobRun).count() == 0  # rolled back with the failed request


def test_create_project_replays_same_resource_and_is_tenant_scoped() -> None:
    ta, tb = uuid.uuid4(), uuid.uuid4()
    try:
        ha = {**_headers(ta, uuid.uuid4()), "Idempotency-Key": "same-key"}
        hb = {**_headers(tb, uuid.uuid4()), "Idempotency-Key": "same-key"}
        first = client.post("/v1/projects", json={"name": "A", "slug": "a"}, headers=ha)
        assert first.status_code == 201, first.text
        again = client.post("/v1/projects", json={"name": "A", "slug": "a"}, headers=ha)
        assert again.status_code == 201
        assert again.json()["id"] == first.json()["id"]
        # Without the key this would be a 409 slug conflict — the key made the retry safe.
        # Another tenant reusing the same client key is an unrelated request.
        other = client.post("/v1/projects", json={"name": "B", "slug": "b"}, headers=hb)
        assert other.status_code == 201
        assert other.json()["id"] != first.json()["id"]
        assert "idempotent-replayed" not in other.headers
    finally:
        for t in (ta, tb):
            with tenant_session(t) as s:
                s.query(JobRun).delete()
                s.query(Project).delete()
                s.query(Tenant).delete()
