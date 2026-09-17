"""Opportunity + plan + approval + change API over HTTP (A-TO-Z-PLAN.md §K.4) — the minimal
approval console the dashboard is built against. Had zero HTTP-level test coverage before this;
added while building the dashboard exposed the gap."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.main import app
from fastapi.testclient import TestClient

from db.models.evidence import Evidence, EvidenceLink
from db.models.identity import Tenant
from db.models.opportunity import Opportunity
from db.models.project import Project
from db.models.safety import Approval, Change, Plan, PlanStep
from db.session import tenant_session

client = TestClient(app)
UTC = dt.UTC


def _headers(tenant: uuid.UUID, user: uuid.UUID, role: str = "owner") -> dict[str, str]:
    return {"x-dev-tenant": str(tenant), "x-dev-user": str(user), "x-dev-role": role}


def _seed_opportunity(t: uuid.UUID, p: uuid.UUID) -> uuid.UUID:
    now = dt.datetime.now(UTC)
    with tenant_session(t, p) as s:
        opp = Opportunity(
            tenant_id=t, project_id=p, type="fix_technical_issue", normalized_key="k1",
            title="Fix missing canonical", detector="technical", first_seen=now, last_seen=now,
        )
        s.add(opp)
        s.flush()
        # content_hash is unique per (tenant_id, content_hash, kind) — NOT per-project — so a
        # fixed constant breaks the moment a test seeds two projects under the same tenant.
        ev = Evidence(
            tenant_id=t, project_id=p, kind="http_response", provider="firsthand-crawl",
            parser="seo_core.crawl.parser", parser_version="0.1.0",
            content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            collected_at=now, confidence=0.95,
        )
        s.add(ev)
        s.flush()
        s.add(EvidenceLink(
            tenant_id=t, project_id=p, evidence_id=ev.id, subject_type="opportunity",
            subject_id=opp.id,
        ))
        return opp.id


@pytest.fixture
def project():
    t, p = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="assisted"))
    yield t, p
    with tenant_session(t, p) as s:
        for m in (Approval, Change, PlanStep, Plan, EvidenceLink, Evidence, Opportunity):
            s.query(m).delete()
    with tenant_session(t) as s:
        s.query(Project).delete()
        s.query(Tenant).delete()


def test_list_and_evidence(project: tuple[uuid.UUID, uuid.UUID]) -> None:
    t, p = project
    oid = _seed_opportunity(t, p)
    h = _headers(t, uuid.uuid4())

    listed = client.get("/v1/opportunities", headers=h)
    assert listed.status_code == 200, listed.text
    assert any(o["id"] == str(oid) for o in listed.json())

    ev = client.get(f"/v1/opportunities/{oid}/evidence", headers=h)
    assert ev.status_code == 200
    assert len(ev.json()) == 1
    assert ev.json()[0]["kind"] == "http_response"


def test_project_id_filter_isolates_two_projects_in_the_same_tenant() -> None:
    """The dashboard is always looking at one project at a time — before the `project_id` query
    param was added, this endpoint mixed every project's opportunities together for a tenant."""
    t, p1, p2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with tenant_session(t) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p1, tenant_id=t, name="P1", slug="p1", approval_mode="assisted"))
        s.add(Project(id=p2, tenant_id=t, name="P2", slug="p2", approval_mode="assisted"))
    try:
        oid1 = _seed_opportunity(t, p1)
        oid2 = _seed_opportunity(t, p2)
        h = _headers(t, uuid.uuid4())

        unfiltered = client.get("/v1/opportunities", headers=h)
        assert {o["id"] for o in unfiltered.json()} >= {str(oid1), str(oid2)}

        only_p1 = client.get("/v1/opportunities", params={"project_id": str(p1)}, headers=h)
        ids = {o["id"] for o in only_p1.json()}
        assert str(oid1) in ids
        assert str(oid2) not in ids
    finally:
        for p in (p1, p2):
            with tenant_session(t, p) as s:
                for m in (EvidenceLink, Evidence, Opportunity):
                    s.query(m).filter(m.project_id == p).delete()
        with tenant_session(t) as s:
            s.query(Project).delete()
            s.query(Tenant).delete()


def test_opportunity_with_no_plan_yet_returns_empty_list(
    project: tuple[uuid.UUID, uuid.UUID],
) -> None:
    t, p = project
    oid = _seed_opportunity(t, p)
    r = client.get(f"/v1/opportunities/{oid}/plans", headers=_headers(t, uuid.uuid4()))
    assert r.status_code == 200
    assert r.json() == []


def test_plan_lookup_by_opportunity_then_detail_then_approve(
    project: tuple[uuid.UUID, uuid.UUID],
) -> None:
    t, p = project
    oid = _seed_opportunity(t, p)
    with tenant_session(t, p) as s:
        plan = Plan(
            tenant_id=t, project_id=p, opportunity_id=oid, state="awaiting_approval",
            root_cause="missing canonical tag", chosen_solution="add rel=canonical",
            requires_approval=True, max_action_class="LOW_RISK_WRITE",
        )
        s.add(plan)
        s.flush()
        s.add(PlanStep(
            tenant_id=t, project_id=p, plan_id=plan.id, ordinal=1, objective="add canonical",
            tool="cms.patch", action_class="LOW_RISK_WRITE", permission="write",
            idempotency_key=f"plan:{plan.id}:step:1",
        ))
        pid = plan.id

    h = _headers(t, uuid.uuid4())

    found = client.get(f"/v1/opportunities/{oid}/plans", headers=h)
    assert found.status_code == 200
    assert [row["id"] for row in found.json()] == [str(pid)]

    detail = client.get(f"/v1/plans/{pid}", headers=h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["opportunity_id"] == str(oid)
    assert len(detail.json()["steps"]) == 1

    operator = _headers(t, uuid.uuid4(), role="operator")
    approved = client.post(
        f"/v1/plans/{pid}/approve", json={"decision": "approved", "note": "looks safe"},
        headers=operator,
    )
    assert approved.status_code == 201, approved.text

    with tenant_session(t, p) as s:
        assert s.get(Plan, pid).state == "approved"
        assert s.query(Approval).filter(Approval.plan_id == pid).one().decision == "approved"


def test_approve_requires_a_note() -> None:
    t, p, u = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with tenant_session(t) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="assisted"))
    try:
        oid = _seed_opportunity(t, p)
        with tenant_session(t, p) as s:
            plan = Plan(
                tenant_id=t, project_id=p, opportunity_id=oid, state="awaiting_approval",
                requires_approval=True, max_action_class="LOW_RISK_WRITE",
            )
            s.add(plan)
            s.flush()
            pid = plan.id

        r = client.post(
            f"/v1/plans/{pid}/approve", json={"decision": "approved"},
            headers=_headers(t, u, role="operator"),
        )
        assert r.status_code == 400
    finally:
        with tenant_session(t, p) as s:
            for m in (Approval, Plan, EvidenceLink, Evidence, Opportunity):
                s.query(m).delete()
        with tenant_session(t) as s:
            s.query(Project).delete()
            s.query(Tenant).delete()


def test_changes_list(project: tuple[uuid.UUID, uuid.UUID]) -> None:
    t, p = project
    with tenant_session(t, p) as s:
        s.add(Change(
            tenant_id=t, project_id=p, adapter="git_pr", state="applied", target="/about",
            action_class="LOW_RISK_WRITE", rollback_strategy="revert commit",
            side_effect_key=f"git_pr:/about:{uuid.uuid4().hex[:12]}",
            applied_at=dt.datetime.now(UTC),
        ))
    r = client.get("/v1/changes", headers=_headers(t, uuid.uuid4()))
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["adapter"] == "git_pr"
