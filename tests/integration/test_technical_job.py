"""technical.analyze against Neon (A-TO-Z-PLAN.md §Phase 3 acceptance).

Seeds a crawl_run + results + snapshots + evidence, runs the job, and checks that seo_issues
rows are written, linked to the evidence snapshot, and idempotent on re-run."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from db.models.crawl import CrawlResult, CrawlRun, PageSnapshot
from db.models.events import OutboxEvent
from db.models.evidence import Evidence, EvidenceLink
from db.models.identity import Tenant
from db.models.issues import SeoIssue
from db.models.project import Project, Website
from db.session import tenant_session

UTC = dt.UTC


@pytest.fixture
def crawled():
    t, p, w, run = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = dt.datetime.now(UTC)
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="read_only"))
        s.add(Website(id=w, tenant_id=t, project_id=p, origin="https://shop.test", verified=True))
        s.flush()
        s.add(CrawlRun(id=run, tenant_id=t, project_id=p, website_id=w, state="completed",
                       tier_requested="http", stats={"robots_has_sitemap": False, "sitemap_urls": []},
                       started_at=now, finished_at=now))
        s.flush()
        for i, (path, title, status) in enumerate([
            ("/", "Home Page Title", 200),
            ("/no-title", None, 200),
            ("/broken", "Broken", 404),
        ]):
            snap_id = uuid.uuid4()
            s.add(PageSnapshot(
                id=snap_id, tenant_id=t, project_id=p, crawl_run_id=run,
                url=f"https://shop.test{path}", url_hash=f"h{i}",
                final_url=f"https://shop.test{path}", tier="http", http_status=status,
                content_hash=f"c{i}", content_fingerprint=f"fp{i:016x}", fetched_at=now,
            ))
            ev = Evidence(
                tenant_id=t, project_id=p, kind="http_response",
                source_url=f"https://shop.test{path}", crawl_run_id=run, snapshot_id=snap_id,
                content_hash=f"c{i}", provider="firsthand-crawl", collected_at=now, confidence=0.98,
            )
            s.add(ev)
            s.flush()
            s.add(CrawlResult(
                tenant_id=t, project_id=p, crawl_run_id=run, snapshot_id=snap_id,
                url=f"https://shop.test{path}", url_hash=f"h{i}", http_status=status,
                title=title, meta_description=("d" if title else None),
                canonical=f"https://shop.test{path}", h1=("H" if path != "/no-title" else None),
                headings=({"h1": ["H"]} if path != "/no-title" else {}),
                word_count=400, internal_links=(["https://shop.test/broken"] if path == "/" else []),
                schema_blocks=[{"@type": "WebPage"}],
            ))
    yield t, p, run
    with tenant_session(t, p) as s:
        for m in (EvidenceLink, SeoIssue, Evidence, CrawlResult, PageSnapshot, CrawlRun,
                  OutboxEvent, Website, Project, Tenant):
            s.query(m).delete()


def test_analyze_writes_linked_issues_and_is_idempotent(crawled) -> None:
    from worker.jobs.technical import run

    t, p, run_id = crawled
    out1 = run(str(t), str(p), str(run_id))
    assert out1["created"] >= 3  # status_4xx, title_missing, broken_internal_link, ...

    with tenant_session(t, p) as s:
        issues = s.query(SeoIssue).all()
        codes = {i.check_code for i in issues}
        assert {"status_4xx", "title_missing", "broken_internal_link"} <= codes

        title_issue = next(i for i in issues if i.check_code == "title_missing")
        link = s.query(EvidenceLink).filter(
            EvidenceLink.subject_type == "issue", EvidenceLink.subject_id == title_issue.id
        ).one()
        ev = s.get(Evidence, link.evidence_id)
        assert ev.kind == "http_response"

        assert s.query(OutboxEvent).filter(OutboxEvent.type == "seo.issue.detected").count() == 1

    # re-run: no new issues, last_seen bumped
    out2 = run(str(t), str(p), str(run_id))
    assert out2["created"] == 0
    with tenant_session(t, p) as s:
        assert s.query(SeoIssue).count() == out1["created"]
        assert all(i.seen_count == 2 for i in s.query(SeoIssue).all())
