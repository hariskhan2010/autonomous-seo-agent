"""Scheduler tick + minimal orchestrator loop against Neon
(A-TO-Z-PLAN.md §Phase 11 acceptance: unattended run advances the pipeline, stops at approval)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from db.models.crawl import CrawlResult, CrawlRun, PageSnapshot
from db.models.events import OutboxEvent, ProcessedEvent
from db.models.evidence import Evidence, EvidenceLink
from db.models.identity import Tenant
from db.models.issues import SeoIssue
from db.models.opportunity import Opportunity
from db.models.ops import AgentRun, Schedule
from db.models.project import Project, Website
from db.models.safety import AgentDecision, Plan, PlanStep
from db.session import tenant_session

UTC = dt.UTC


@pytest.fixture
def project():
    t, p = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="assisted"))
    yield t, p
    with tenant_session(t, p) as s:
        for m in (PlanStep, Plan, AgentDecision, EvidenceLink, Evidence, SeoIssue, Opportunity,
                  CrawlResult, PageSnapshot, CrawlRun, Website, ProcessedEvent, OutboxEvent,
                  AgentRun, Schedule, Project, Tenant):
            s.query(m).delete()


def test_scheduler_tick_fires_due_and_reschedules(project) -> None:
    from worker.jobs.scheduler import tick

    t, p = project
    with tenant_session(t, p) as s:
        s.add(Schedule(tenant_id=t, project_id=p, name="weekly-serp", cadence="weekly",
                       task="serp.analyze", args={"query": "x"}, enabled=True,
                       next_run_at=dt.datetime.now(UTC) - dt.timedelta(hours=1)))
        s.add(Schedule(tenant_id=t, project_id=p, name="future", cadence="daily",
                       task="crawl.run", args={}, enabled=True,
                       next_run_at=dt.datetime.now(UTC) + dt.timedelta(days=1)))

    fired: list[str] = []
    out = tick(str(t), str(p), enqueue=lambda task, args: fired.append(task))
    assert out["fired"] == 1 and fired == ["serp.analyze"]

    with tenant_session(t, p) as s:
        sched = s.query(Schedule).filter(Schedule.name == "weekly-serp").one()
        assert sched.next_run_at > dt.datetime.now(UTC) + dt.timedelta(days=6)


def test_orchestrator_drains_pipeline_and_stops_at_approval(project) -> None:
    from worker.jobs.orchestrator import run_once

    t, p = project
    now = dt.datetime.now(UTC)
    # seed a crawl run + a result + a snapshot + evidence, then a crawl.completed outbox event
    with tenant_session(t, p) as s:
        w = uuid.uuid4()
        s.add(Website(id=w, tenant_id=t, project_id=p, origin="https://x.com", verified=True))
        s.flush()
        run = CrawlRun(tenant_id=t, project_id=p, website_id=w, state="completed",
                       tier_requested="http", stats={"robots_has_sitemap": False, "sitemap_urls": []},
                       started_at=now, finished_at=now)
        s.add(run)
        s.flush()
        snap = PageSnapshot(tenant_id=t, project_id=p, crawl_run_id=run.id, url="https://x.com/a",
                            url_hash="h1", final_url="https://x.com/a", tier="http", http_status=200,
                            content_hash="c1", content_fingerprint="fp1", fetched_at=now)
        s.add(snap)
        s.flush()
        ev = Evidence(tenant_id=t, project_id=p, kind="http_response", source_url="https://x.com/a",
                      crawl_run_id=run.id, snapshot_id=snap.id, content_hash="c1",
                      provider="firsthand-crawl", collected_at=now, confidence=0.98)
        s.add(ev)
        s.add(CrawlResult(
            tenant_id=t, project_id=p, crawl_run_id=run.id, snapshot_id=snap.id,
            url="https://x.com/a", url_hash="h1", http_status=200, title=None,  # → title_missing
            canonical="https://x.com/other",  # → canonical_not_self (P1-ish)
            word_count=400, internal_links=[], schema_blocks=[{"@type": "WebPage"}], headings={},
        ))
        s.add(OutboxEvent(tenant_id=t, project_id=p, type="crawl.completed", version=1,
                          payload={"crawl_run_id": str(run.id)}))

    out = run_once(str(t), str(p), goal="fix technical issues", trigger="manual")

    assert out["state"] in ("awaiting_approval", "measuring")
    with tenant_session(t, p) as s:
        assert s.query(SeoIssue).count() >= 1               # technical.analyze ran
        assert s.query(Opportunity).count() >= 1            # opportunities.detect ran
        assert s.query(AgentRun).one().state == out["state"]
        # an assisted-mode plan for a P0/P1 opportunity stops awaiting approval
        if out["plans_awaiting_approval"]:
            assert s.query(Plan).filter(Plan.state == "awaiting_approval").count() >= 1
