"""Celery app (A-TO-Z-PLAN.md §AA — short, stateless, retryable unit jobs only).
The long autonomous loop runs on Temporal from Phase 11, not here."""

from __future__ import annotations

from celery import Celery

from common.logging import configure_logging
from common.settings import settings

configure_logging()

celery_app = Celery(
    "seo",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    # `crawl.run_tier2` needs a real browser (Phase 2/13) — routed to the dedicated `render`
    # queue, consumed ONLY by the Tier-2 container (`infra/Dockerfile.playwright`). The default
    # `worker` service never launches a browser and should never consume this queue.
    task_routes={"crawl.run_tier2": {"queue": "render"}},
)


@celery_app.task(name="meta.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"


@celery_app.task(name="crawl.run", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def crawl_run(
    self: object, tenant_id: str, project_id: str, website_id: str,
    options: dict[str, object] | None = None, correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.crawl import run

    return run(tenant_id, project_id, website_id, options, correlation_id)


@celery_app.task(name="crawl.run_tier2", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def crawl_run_tier2(
    self: object, tenant_id: str, project_id: str, website_id: str,
    options: dict[str, object] | None = None, correlation_id: str | None = None,
) -> dict[str, object]:
    """Same job as `crawl.run`, forced onto `tier="browser"` (Phase 2/13) — a distinct task name
    purely so `task_routes` can send it to the `render` queue without inspecting kwargs; the
    lightweight `worker` service never consumes that queue, so a Tier-2 job never lands somewhere
    without a browser."""
    from worker.jobs.crawl import run

    opts = {**(options or {}), "tier": "browser"}
    return run(tenant_id, project_id, website_id, opts, correlation_id)


@celery_app.task(name="technical.analyze", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def technical_analyze(
    self: object, tenant_id: str, project_id: str, crawl_run_id: str,
    correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.technical import run

    return run(tenant_id, project_id, crawl_run_id, correlation_id)


@celery_app.task(name="keywords.ingest", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def keywords_ingest(
    self: object, tenant_id: str, project_id: str, terms: list[dict[str, object]] | list[str],
    locale: str = "en-US", correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.keywords import ingest

    return ingest(tenant_id, project_id, terms, locale, correlation_id)


@celery_app.task(name="serp.analyze", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def serp_analyze(
    self: object, tenant_id: str, project_id: str, query: str,
    own_domain: str | None = None, competitor_domains: list[str] | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.keywords import analyze_query

    return analyze_query(
        tenant_id, project_id, query, own_domain=own_domain,
        competitor_domains=competitor_domains, correlation_id=correlation_id,
    )


@celery_app.task(name="content.analyze", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def content_analyze(
    self: object, tenant_id: str, project_id: str, crawl_run_id: str,
    correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.content import run

    return run(tenant_id, project_id, crawl_run_id, correlation_id)


@celery_app.task(name="graph.build", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def graph_build(
    self: object, tenant_id: str, project_id: str, crawl_run_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.graph import run

    return run(tenant_id, project_id, crawl_run_id, correlation_id)


@celery_app.task(name="opportunities.detect", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def opportunities_detect(
    self: object, tenant_id: str, project_id: str, correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.opportunities import run

    return run(tenant_id, project_id, correlation_id)


@celery_app.task(name="plan.build", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def plan_build(self: object, tenant_id: str, project_id: str, opportunity_id: str,
               correlation_id: str | None = None) -> dict[str, object]:
    from worker.jobs.planning import build

    return build(tenant_id, project_id, opportunity_id, correlation_id)


@celery_app.task(name="plan.execute", bind=True, max_retries=1)  # type: ignore[untyped-decorator]
def plan_execute(self: object, tenant_id: str, project_id: str, plan_id: str, repo_path: str,
                 correlation_id: str | None = None) -> dict[str, object]:
    from worker.jobs.planning import execute

    return execute(
        tenant_id, project_id, plan_id, repo_path=repo_path, correlation_id=correlation_id
    )


@celery_app.task(name="metrics.ingest", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def metrics_ingest(self: object, tenant_id: str, project_id: str,
                   days: int = 90, correlation_id: str | None = None) -> dict[str, object]:
    from worker.jobs.analytics import ingest
    return ingest(tenant_id, project_id, days=days, correlation_id=correlation_id)


@celery_app.task(name="anomaly.detect", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def anomaly_detect(self: object, tenant_id: str, project_id: str, metric: str,
                   correlation_id: str | None = None) -> dict[str, object]:
    from worker.jobs.analytics import detect
    return detect(tenant_id, project_id, metric, correlation_id)


@celery_app.task(name="experiment.evaluate", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def experiment_evaluate(self: object, tenant_id: str, project_id: str, experiment_id: str,
                        correlation_id: str | None = None) -> dict[str, object]:
    from worker.jobs.analytics import evaluate
    return evaluate(tenant_id, project_id, experiment_id, correlation_id)


@celery_app.task(name="geo.battery", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def geo_battery(
    self: object, tenant_id: str, project_id: str, brand: str, own_domain: str,
    cluster_id: str | None = None, correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.geo import battery

    return battery(
        tenant_id, project_id, cluster_id=cluster_id, brand=brand,
        own_domain=own_domain, correlation_id=correlation_id,
    )


@celery_app.task(name="geo.seed_prompts", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def geo_seed_prompts(
    self: object, tenant_id: str, project_id: str, cluster_id: str, brand: str, category: str,
    seed_keywords: list[str] | None = None, competitor_names: list[str] | None = None,
) -> dict[str, object]:
    from worker.jobs.geo import seed_prompts

    return seed_prompts(
        tenant_id, project_id, cluster_id=cluster_id, brand=brand, category=category,
        seed_keywords=seed_keywords, competitor_names=competitor_names,
    )


@celery_app.task(name="vitals.analyze", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def vitals_analyze(
    self: object, tenant_id: str, project_id: str, url: str, strategy: str = "mobile",
    correlation_id: str | None = None,
) -> dict[str, object]:
    from worker.jobs.vitals import analyze

    return analyze(tenant_id, project_id, url, strategy=strategy, correlation_id=correlation_id)


@celery_app.task(name="events.relay", bind=True)  # type: ignore[untyped-decorator]
def events_relay(self: object, tenant_id: str, project_id: str) -> dict[str, object]:
    import uuid as _uuid

    import worker.pipeline  # noqa: F401  (registers consumers)
    from db.session import tenant_session
    from events.bus import dispatch_pending

    with tenant_session(_uuid.UUID(tenant_id), _uuid.UUID(project_id)) as s:
        return dict(dispatch_pending(s))


@celery_app.task(name="scheduler.tick", bind=True)  # type: ignore[untyped-decorator]
def scheduler_tick(self: object, tenant_id: str, project_id: str) -> dict[str, object]:
    from worker.jobs.scheduler import tick

    def _enqueue(task: str, args: dict[str, object]) -> None:
        celery_app.send_task(task, kwargs=args)

    return tick(tenant_id, project_id, enqueue=_enqueue)


@celery_app.task(name="orchestrator.run_once", bind=True, max_retries=1)  # type: ignore[untyped-decorator]
def orchestrator_run_once(self: object, tenant_id: str, project_id: str,
                          goal: str | None = None, trigger: str = "schedule",
                          correlation_id: str | None = None) -> dict[str, object]:
    from worker.jobs.orchestrator import run_once

    return run_once(
        tenant_id, project_id, goal=goal, trigger=trigger, correlation_id=correlation_id,
    )
