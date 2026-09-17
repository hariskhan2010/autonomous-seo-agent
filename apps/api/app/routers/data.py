"""Read API for the pipeline outputs (A-TO-Z-PLAN.md §Phase 12, §41).

Cursor-free simple listings for now; all tenant-scoped via `get_db`, with an optional
`project_id` filter (same convention as `websites.py::list_websites`) for a tenant running more
than one project — added while building the dashboard, which is always looking at one project at
a time. Reports served as Markdown."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal
from app.deps import get_db, get_principal
from db.models.analytics import Anomaly, Experiment
from db.models.crawl import CrawlRun
from db.models.geo import AiVisibilityScore
from db.models.issues import SeoIssue
from db.models.keywords import Keyword, KeywordCluster
from db.models.opportunity import Opportunity
from db.models.safety import Change
from reporting import executive_report, technical_report

router = APIRouter(tags=["data"])


@router.get("/crawls")
def crawls(
    project_id: uuid.UUID | None = Query(default=None), limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(CrawlRun).order_by(CrawlRun.created_at.desc()).limit(limit)
    if project_id is not None:
        q = q.where(CrawlRun.project_id == project_id)
    rows = db.execute(q).scalars()
    return [{"id": str(c.id), "website_id": str(c.website_id), "state": c.state,
             "tier": c.tier_requested, "stats": c.stats,
             "finished_at": c.finished_at.isoformat() if c.finished_at else None} for c in rows]


@router.get("/issues")
def issues(
    project_id: uuid.UUID | None = Query(default=None), severity: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(SeoIssue).where(SeoIssue.status.in_(("open", "regressed")))
    if project_id is not None:
        q = q.where(SeoIssue.project_id == project_id)
    if severity:
        q = q.where(SeoIssue.severity == severity)
    return [{"id": str(i.id), "check_code": i.check_code, "category": i.category,
             "severity": i.severity, "title": i.title, "url": i.url, "fix": i.fix,
             "seen_count": i.seen_count} for i in db.execute(q).scalars()]


@router.get("/keywords")
def keywords(db: Session = Depends(get_db)) -> dict[str, object]:
    kws = db.execute(select(Keyword)).scalars().all()
    clusters = db.execute(select(KeywordCluster).order_by(KeywordCluster.volume_sum.desc())).scalars()
    return {
        "count": len(kws),
        "clusters": [{"name": c.name, "size": c.size, "volume_sum": c.volume_sum,
                      "primary_intent": c.primary_intent, "intents": c.intents} for c in clusters],
    }


@router.get("/anomalies")
def anomalies(
    project_id: uuid.UUID | None = Query(default=None), db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(Anomaly).where(Anomaly.status == "open").order_by(Anomaly.detected_on.desc())
    if project_id is not None:
        q = q.where(Anomaly.project_id == project_id)
    rows = db.execute(q).scalars()
    return [{"id": str(a.id), "metric": a.metric, "direction": a.direction,
             "magnitude_pct": float(a.magnitude_pct), "detected_on": a.detected_on.isoformat(),
             "investigation": a.investigation} for a in rows]


@router.get("/experiments")
def experiments(
    project_id: uuid.UUID | None = Query(default=None), db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(Experiment).order_by(Experiment.created_at.desc())
    if project_id is not None:
        q = q.where(Experiment.project_id == project_id)
    rows = db.execute(q).scalars()
    return [{"id": str(e.id), "type": e.experiment_type, "hypothesis": e.hypothesis,
             "state": e.state, "verdict": e.verdict,
             "confidence": float(e.confidence) if e.confidence is not None else None,
             "result": e.result, "confounders": e.confounders} for e in rows]


@router.get("/geo/visibility")
def geo_visibility(
    project_id: uuid.UUID | None = Query(default=None), db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(AiVisibilityScore).order_by(AiVisibilityScore.week.desc())
    if project_id is not None:
        q = q.where(AiVisibilityScore.project_id == project_id)
    rows = db.execute(q).scalars()
    return [{"provider": v.provider, "week": v.week.isoformat(), "score": float(v.score),
             "brand_mention_rate": float(v.brand_mention_rate),
             "own_citation_rate": float(v.own_citation_rate), "prompts_run": v.prompts_run}
            for v in rows]


@router.get("/reports/executive", response_class=Response)
def report_executive(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> Response:
    opps: list[dict[str, object]] = [{"priority": o.priority, "type": o.type, "title": o.title, "score": float(o.score),
             "action_class": o.action_class}
            for o in db.execute(select(Opportunity).where(Opportunity.status != "completed")).scalars()]
    changes: list[dict[str, object]] = [{"target": c.target, "state": c.state, "verified": c.state == "verified",
                "applied_at": c.applied_at.isoformat() if c.applied_at else None}
               for c in db.execute(select(Change).order_by(Change.created_at.desc()).limit(20)).scalars()]
    vis = {v.provider: float(v.score) for v in
           db.execute(select(AiVisibilityScore)).scalars()}
    rep = executive_report(project_name=str(principal.tenant_id)[:8], metrics={},
                           open_opportunities=opps, recent_changes=changes, ai_visibility=vis)
    return Response(content=rep.markdown, media_type="text/markdown")


@router.get("/reports/technical", response_class=Response)
def report_technical(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> Response:
    by_sev: dict[str, list[dict[str, object]]] = {}
    for i in db.execute(select(SeoIssue).where(SeoIssue.status.in_(("open", "regressed")))).scalars():
        by_sev.setdefault(i.severity, []).append(
            {"check_code": i.check_code, "url": i.url, "url_pattern": i.url_pattern, "fix": i.fix}
        )
    rep = technical_report(project_name=str(principal.tenant_id)[:8], issues_by_severity=by_sev)
    return Response(content=rep.markdown, media_type="text/markdown")
