"""vitals.analyze against Neon (A-TO-Z-PLAN.md §Phase 3 — Core Web Vitals, deferred item).

Runs the job with the fake provider (a canned poor LCP, everything else good), and checks that
an `evidence` row (kind='pagespeed') and a linked `seo_issues` row are written, idempotently."""

from __future__ import annotations

import uuid

import pytest

from db.models.events import OutboxEvent
from db.models.evidence import Evidence, EvidenceLink
from db.models.identity import Tenant
from db.models.issues import SeoIssue
from db.models.project import Project
from db.session import tenant_session


@pytest.fixture
def project():
    t, p = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="read_only"))
    yield t, p
    with tenant_session(t, p) as s:
        for m in (EvidenceLink, SeoIssue, Evidence, OutboxEvent, Project, Tenant):
            s.query(m).delete()


def test_vitals_analyze_writes_evidence_and_linked_issue_idempotently(project) -> None:
    from worker.jobs.vitals import analyze

    t, p = project
    url = "https://shop.test/product"

    out1 = analyze(str(t), str(p), url, use_fake=True)
    assert out1["created"] == 1  # the fake provider's canned poor LCP

    with tenant_session(t, p) as s:
        ev = s.query(Evidence).filter(Evidence.kind == "pagespeed").one()
        assert ev.source_url == url
        assert ev.props["lcp_ms"] == 4200.0

        issue = s.query(SeoIssue).one()
        assert issue.check_code == "cwv_lcp_poor"
        assert issue.url == url

        link = s.query(EvidenceLink).filter(
            EvidenceLink.subject_type == "issue", EvidenceLink.subject_id == issue.id,
        ).one()
        assert link.evidence_id == ev.id

        assert s.query(OutboxEvent).filter(OutboxEvent.type == "vitals.analyzed").count() == 1

    out2 = analyze(str(t), str(p), url, use_fake=True)
    assert out2["created"] == 0
    with tenant_session(t, p) as s:
        assert s.query(SeoIssue).count() == 1
        assert s.query(SeoIssue).one().seen_count == 2
        # identical reading (content-addressed, like page_snapshots) → no new evidence row
        assert s.query(Evidence).filter(Evidence.kind == "pagespeed").count() == 1
