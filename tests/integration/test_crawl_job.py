"""crawl.run end-to-end against Neon, with the network fetch mocked (A-TO-Z-PLAN.md §Phase 2).

Verifies: snapshot + result + evidence rows written, `crawl.completed` in the outbox, and that
a re-run of an unchanged page produces no second snapshot."""

from __future__ import annotations

import uuid

import pytest

from db.models.crawl import CrawlResult, CrawlRun, PageSnapshot
from db.models.events import OutboxEvent
from db.models.evidence import Evidence
from db.models.identity import Tenant
from db.models.project import Project, Website
from db.session import tenant_session
from seo_core.crawl.fetcher import FetchResult

PAGE = (
    "<!doctype html><html><head><title>Home</title>"
    '<meta name="description" content="welcome">'
    '<link rel="canonical" href="https://shop.test/"></head>'
    "<body><h1>Home</h1><p>" + "word " * 60 + "</p>"
    "<a href='/about'>about</a></body></html>"
).encode("utf-8")


@pytest.fixture
def project():
    t, p, w = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="read_only"))
        s.add(Website(id=w, tenant_id=t, project_id=p, origin="https://shop.test", verified=True))
    yield t, p, w
    with tenant_session(t, p) as s:
        for m in (Evidence, CrawlResult, PageSnapshot, CrawlRun, OutboxEvent, Website, Project, Tenant):
            s.query(m).delete()


async def _fake_fetch(url, *, client, allowed_hosts=None, limiter=None, **kw):  # noqa: ANN001
    if url.endswith("robots.txt"):
        return FetchResult(url, url, 404, {}, b"", parseable=False)
    return FetchResult(
        url=url, final_url="https://shop.test/", status=200,
        headers={"content-type": "text/html"}, body=PAGE, parseable=True,
    )


def test_crawl_writes_evidence_and_emits_event(project, monkeypatch: pytest.MonkeyPatch) -> None:
    import worker.jobs.crawl as job

    monkeypatch.setattr(job, "fetch", _fake_fetch)
    t, p, w = project

    out = job.run(str(t), str(p), str(w), {"max_pages": 3})
    assert out["stats"]["fetched"] >= 1

    with tenant_session(t, p) as s:
        assert s.query(PageSnapshot).count() == 1
        assert s.query(CrawlResult).count() == 1
        ev = s.query(Evidence).one()
        assert ev.kind == "http_response" and ev.provider == "firsthand-crawl"
        assert float(ev.confidence) > 0.9
        outbox = s.query(OutboxEvent).filter(OutboxEvent.type == "crawl.completed").one()
        assert outbox.payload["stats"]["fetched"] >= 1
        run = s.query(CrawlRun).one()
        assert run.state == "completed"

    # re-crawl: page unchanged -> no new snapshot
    job.run(str(t), str(p), str(w), {"max_pages": 3})
    with tenant_session(t, p) as s:
        assert s.query(PageSnapshot).count() == 1


def test_crawl_dispatches_to_tier_2_render_when_requested(
    project, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CrawlOptions.tier="browser"` must route the page fetch through
    `seo_core.crawl.render.render`, not Tier 1's `fetch` — proven with a fake `render`, no real
    browser needed (that's `tests/integration/test_render_smoke.py`'s job)."""
    import worker.jobs.crawl as job

    import seo_core.crawl.render as render_module

    render_calls: list[str] = []

    async def _fake_render(url, *, allowed_hosts=None, **kw):  # noqa: ANN001
        render_calls.append(url)
        return FetchResult(
            url=url, final_url="https://shop.test/", status=200,
            headers={"content-type": "text/html"}, body=PAGE, parseable=True,
        )

    monkeypatch.setattr(job, "fetch", _fake_fetch)  # robots.txt/sitemap discovery stays Tier 1
    monkeypatch.setattr(render_module, "render", _fake_render)
    t, p, w = project

    out = job.run(str(t), str(p), str(w), {"max_pages": 3, "tier": "browser"})
    assert out["stats"]["fetched"] >= 1
    assert len(render_calls) >= 1

    with tenant_session(t, p) as s:
        snap = s.query(PageSnapshot).one()
        assert snap.tier == "browser"
