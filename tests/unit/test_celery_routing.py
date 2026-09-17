"""Tier-2 Celery wiring (Phase 2/13): `crawl.run_tier2` is routed to the dedicated `render` queue
and forces `tier="browser"` — the two properties that keep a browser-requiring job off the
browser-less default `worker` image."""

from __future__ import annotations

from worker.app import celery_app, crawl_run_tier2


def test_crawl_run_tier2_is_routed_to_the_render_queue() -> None:
    assert celery_app.conf.task_routes["crawl.run_tier2"]["queue"] == "render"


def test_crawl_run_tier2_forces_the_browser_tier(monkeypatch) -> None:  # noqa: ANN001
    captured = {}

    def _fake_run(tenant_id, project_id, website_id, options, correlation_id):  # noqa: ANN001
        captured["options"] = options
        return {"ok": True}

    import worker.jobs.crawl as crawl_job
    monkeypatch.setattr(crawl_job, "run", _fake_run)

    # `.run` is already bound to the task instance (bind=True) — calling the task object itself
    # instead would go through Celery's dispatch machinery, which isn't what's under test here.
    crawl_run_tier2.run("t", "p", "w", {"max_pages": 5}, "corr-1")
    assert captured["options"]["tier"] == "browser"
    assert captured["options"]["max_pages"] == 5
