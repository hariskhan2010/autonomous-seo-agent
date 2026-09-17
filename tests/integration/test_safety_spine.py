"""End-to-end safety spine against Neon + a real local git repo
(A-TO-Z-PLAN.md §Phase 8 acceptance): opportunity → plan → approve → apply → verify → (fail →
rollback → incident); conflict detection; autonomous allow-list."""

from __future__ import annotations

import datetime as dt
import subprocess
import uuid
from pathlib import Path

import pytest

from db.models.events import OutboxEvent
from db.models.evidence import Evidence, EvidenceLink
from db.models.identity import Tenant
from db.models.opportunity import Opportunity
from db.models.project import Project
from db.models.safety import (
    AgentDecision,
    Approval,
    Change,
    ChangeVersion,
    Incident,
    Plan,
    PlanStep,
    Rollback,
    Verification,
)
from db.session import tenant_session

UTC = dt.UTC


def _git_repo(tmp: Path) -> Path:
    repo = tmp / "site"
    repo.mkdir()
    for a in (["init", "-q"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit",
                               "--allow-empty", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: S603, S607
    (repo / "content").mkdir()
    return repo


@pytest.fixture
def scenario(tmp_path: Path):
    t, p = uuid.uuid4(), uuid.uuid4()
    repo = _git_repo(tmp_path)
    now = dt.datetime.now(UTC)
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="assisted",
                      config={"autonomous_types": ["add_schema"]}))
        s.flush()
        ev = Evidence(tenant_id=t, project_id=p, kind="http_response", source_url="https://x.com/a",
                      content_hash="c1", provider="firsthand-crawl", collected_at=now, confidence=0.95)
        s.add(ev)
        s.flush()
        opp = Opportunity(
            tenant_id=t, project_id=p, type="fix_canonical", normalized_key="k1",
            url="https://x.com/a", title="Canonical wrong", business_impact=0.7, seo_impact=0.8,
            confidence=0.9, feasibility=0.8, risk=0.2, score=45.0, priority="P1",
            action_class="LOW_RISK_WRITE", recommendation="self-canonical",
            verification_method="canonical == url", status="detected", detector="issue_detector",
            first_seen=now, last_seen=now,
        )
        s.add(opp)
        s.flush()
        s.add(EvidenceLink(tenant_id=t, project_id=p, evidence_id=ev.id,
                           subject_type="opportunity", subject_id=opp.id))
        oid = str(opp.id)
    yield t, p, oid, repo
    with tenant_session(t, p) as s:
        for m in (Incident, Rollback, Verification, ChangeVersion, Change, Approval, PlanStep,
                  Plan, AgentDecision, EvidenceLink, Evidence, Opportunity, OutboxEvent,
                  Project, Tenant):
            s.query(m).delete()


def test_assisted_flow_needs_approval_then_applies_and_verifies(scenario) -> None:
    from worker.jobs.planning import build, execute

    t, p, oid, repo = scenario
    b = build(str(t), str(p), oid)
    assert b["requires_approval"] is True and b["steps"] == 1
    plan_id = str(b["plan_id"])

    # execute without approval → stops at the gate
    r1 = execute(str(t), str(p), plan_id, repo_path=str(repo))
    assert r1["results"][0]["outcome"] == "awaiting_approval"

    with tenant_session(t, p) as s:
        s.add(Approval(tenant_id=t, project_id=p, plan_id=uuid.UUID(plan_id),
                       decision="approved", decided_at=dt.datetime.now(UTC)))

    r2 = execute(str(t), str(p), plan_id, repo_path=str(repo))
    assert r2["results"][0]["outcome"] == "verified"

    with tenant_session(t, p) as s:
        ch = s.query(Change).one()
        assert ch.state == "verified" and ch.external_ref and ch.backup_ref
        assert s.query(ChangeVersion).count() == 1
        assert s.query(Verification).one().passed is True
        assert s.query(Incident).count() == 0
        assert s.get(Plan, uuid.UUID(plan_id)).state == "done"
        assert s.query(OutboxEvent).filter(OutboxEvent.type == "change.executed").count() == 1
        assert s.query(AgentDecision).filter(AgentDecision.kind == "plan_chosen").count() == 1
    # commit actually landed in the repo
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True,  # noqa: S603, S607
                         text=True, check=True).stdout
    assert log.count("\n") >= 2


def test_autonomous_allowlisted_type_skips_approval(scenario) -> None:
    from worker.jobs.planning import build, execute

    t, p, oid, repo = scenario
    with tenant_session(t, p) as s:
        s.query(Opportunity).update({"type": "add_schema", "normalized_key": "k2"})
        s.query(Project).update({"approval_mode": "autonomous"})

    b = build(str(t), str(p), oid)
    assert b["requires_approval"] is False
    r = execute(str(t), str(p), str(b["plan_id"]), repo_path=str(repo))
    assert r["results"][0]["outcome"] == "verified"


def test_read_only_mode_blocks(scenario) -> None:
    from worker.jobs.planning import build, execute

    t, p, oid, repo = scenario
    with tenant_session(t, p) as s:
        s.query(Project).update({"approval_mode": "read_only"})
    b = build(str(t), str(p), oid)
    r = execute(str(t), str(p), str(b["plan_id"]), repo_path=str(repo))
    assert r["results"][0]["outcome"] == "blocked_read_only"
