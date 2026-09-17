"""The autonomous pipeline wired as idempotent event consumers (A-TO-Z-PLAN.md §Phase 11, §J).

crawl.completed        → technical.analyze + content.analyze + graph.build
seo.issue.detected     → opportunities.detect
opportunity.created    → plan.build for P0/P1 (assisted → stops at the approval gate)

This is the event-driven core the Orchestrator (Temporal, when available) sits above. Every
consumer records `processed_events`, so redelivery is a no-op. Jobs are invoked in-process here;
in production the consumer enqueues the Celery task instead."""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from events.bus import Event, register_consumer

log = structlog.get_logger("events.pipeline")


def _on_crawl_completed(ev: Event, _s: Session) -> None:
    from worker.jobs.content import run as content_run
    from worker.jobs.graph import run as graph_run
    from worker.jobs.technical import run as technical_run

    rid = str(ev.payload["crawl_run_id"])
    t, p = str(ev.tenant_id), str(ev.project_id)
    technical_run(t, p, rid, ev.correlation_id)
    content_run(t, p, rid, ev.correlation_id)
    graph_run(t, p, rid, ev.correlation_id)


def _on_issue_detected(ev: Event, _s: Session) -> None:
    from worker.jobs.opportunities import run as opp_run

    opp_run(str(ev.tenant_id), str(ev.project_id), ev.correlation_id)


def _on_opportunity_created(ev: Event, s: Session) -> None:
    from db.models.opportunity import Opportunity
    from worker.jobs.planning import build as plan_build

    for opp in s.query(Opportunity).filter(
        Opportunity.project_id == ev.project_id,
        Opportunity.status == "detected",
        Opportunity.priority.in_(("P0", "P1")),
    ).all():
        plan_build(str(ev.tenant_id), str(ev.project_id), str(opp.id), ev.correlation_id)


def register_pipeline() -> None:
    register_consumer("pipeline.crawl_completed", "crawl.completed", _on_crawl_completed)
    register_consumer("pipeline.issue_detected", "seo.issue.detected", _on_issue_detected)
    register_consumer("pipeline.opportunity_created", "opportunity.created", _on_opportunity_created)


register_pipeline()
