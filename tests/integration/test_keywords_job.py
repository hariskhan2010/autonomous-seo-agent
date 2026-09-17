"""keywords.ingest + serp.analyze against Neon with the fake SERP provider
(A-TO-Z-PLAN.md §Phase 4 acceptance)."""

from __future__ import annotations

import uuid

import pytest

from db.models.events import OutboxEvent
from db.models.evidence import Evidence
from db.models.identity import Tenant
from db.models.keywords import Keyword, KeywordCluster, SearchIntent
from db.models.project import Project
from db.models.serp import SerpEntity, SerpFeature, SerpResult, SerpRun
from db.session import tenant_session


@pytest.fixture
def project():
    t, p = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="read_only"))
    yield t, p
    with tenant_session(t, p) as s:
        for m in (SearchIntent, SerpEntity, SerpFeature, SerpResult, SerpRun, Evidence,
                  Keyword, KeywordCluster, OutboxEvent, Project, Tenant):
            s.query(m).delete()


def test_ingest_classifies_clusters_and_persists(project) -> None:
    from worker.jobs.keywords import ingest

    t, p = project
    out = ingest(str(t), str(p), [
        {"term": "gemstone rings", "volume": 1000},
        {"term": "gemstone ring", "volume": 800},
        {"term": "buy gemstone rings online", "volume": 400},
        {"term": "how to clean gemstone rings"},
    ])
    assert out["keywords"] == 4

    with tenant_session(t, p) as s:
        buy = s.query(Keyword).filter(Keyword.normalized == "buy gemstone rings online").one()
        labels = {si.label for si in s.query(SearchIntent).filter(SearchIntent.keyword_id == buy.id)}
        assert "transactional" in labels
        assert buy.cluster_id is not None
        clusters = s.query(KeywordCluster).all()
        assert any(c.size >= 2 for c in clusters)
        assert s.query(OutboxEvent).filter(OutboxEvent.type == "keywords.ingested").count() == 1

    # re-ingest same terms → no duplicate keywords
    ingest(str(t), str(p), ["gemstone rings"])
    with tenant_session(t, p) as s:
        assert s.query(Keyword).filter(Keyword.normalized == "gemstone rings").count() == 1


def test_serp_analyze_persists_run_results_features_evidence(project) -> None:
    from worker.jobs.keywords import analyze_query

    t, p = project
    out = analyze_query(
        str(t), str(p), "how to clean gemstone rings",
        own_domain="shop.example.com", competitor_domains=["jewelry.com"], use_fake=True,
    )
    assert "people_also_ask" in out["feature_types"]

    with tenant_session(t, p) as s:
        run = s.query(SerpRun).one()
        assert run.provider == "fake"
        assert s.query(SerpResult).filter(SerpResult.serp_run_id == run.id).count() == 4
        own = s.query(SerpResult).filter(SerpResult.serp_run_id == run.id, SerpResult.is_own).one()
        assert own.position == 3
        assert s.query(SerpFeature).filter(SerpFeature.serp_run_id == run.id).count() >= 2
        assert s.query(SerpEntity).filter(SerpEntity.serp_run_id == run.id).count() >= 1
        ev = s.query(Evidence).filter(Evidence.kind == "serp_snapshot").one()
        assert ev.serp_run_id == run.id and float(ev.confidence) > 0.8
        assert s.query(OutboxEvent).filter(OutboxEvent.type == "serp.analyzed").count() == 1
