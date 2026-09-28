"""Read API for the pipeline outputs (A-TO-Z-PLAN.md §Phase 12, §41).

All tenant-scoped via `get_db`, with an optional
`project_id` filter (same convention as `websites.py::list_websites`) for a tenant running more
than one project — added while building the dashboard, which is always looking at one project at
a time. Every listing takes optional `?limit=&cursor=` keyset pagination (`app/pagination.py`):
the body stays a bare array (backward compatible) and the next page's cursor comes back in the
`X-Next-Cursor` header. Omitting both keeps the legacy full listing. Reports served as Markdown."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal
from app.deps import get_db, get_principal
from app.pagination import MAX_LIMIT, apply_keyset, effective_limit, finish_page, paginate
from db.models.analytics import Anomaly, Experiment
from db.models.crawl import CrawlRun
from db.models.geo import AiVisibilityScore
from db.models.issues import SeoIssue
from db.models.keywords import Keyword, KeywordCluster
from db.models.opportunity import Opportunity
from db.models.safety import Change
from reporting import executive_report, technical_report

router = APIRouter(tags=["data"])

_CURSOR = Query(default=None, description="Opaque cursor from a previous `X-Next-Cursor` header.")
_LIMIT = Query(default=None, ge=1, le=MAX_LIMIT,
               description="Page size. Omit (with no cursor) for the full, unpaginated listing.")


@router.get("/crawls")
def crawls(
    request: Request, response: Response,
    project_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100), cursor: str | None = _CURSOR,
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    # The one listing that was already capped (default 20) — keeps that default.
    q = select(CrawlRun)
    if project_id is not None:
        q = q.where(CrawlRun.project_id == project_id)
    rows = paginate(db, request, response, q, (CrawlRun.created_at, CrawlRun.id),
                    scope="crawls", cursor=cursor, limit=limit)
    return [{"id": str(c.id), "website_id": str(c.website_id), "state": c.state,
             "tier": c.tier_requested, "stats": c.stats,
             "finished_at": c.finished_at.isoformat() if c.finished_at else None} for c in rows]


@router.get("/issues")
def issues(
    request: Request, response: Response,
    project_id: uuid.UUID | None = Query(default=None), severity: str | None = Query(default=None),
    limit: int | None = _LIMIT, cursor: str | None = _CURSOR,
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(SeoIssue).where(SeoIssue.status.in_(("open", "regressed")))
    if project_id is not None:
        q = q.where(SeoIssue.project_id == project_id)
    if severity:
        q = q.where(SeoIssue.severity == severity)
    # Previously unordered; newest-first is now the stable order pagination needs.
    rows = paginate(db, request, response, q, (SeoIssue.created_at, SeoIssue.id),
                    scope="issues", cursor=cursor, limit=limit)
    return [{"id": str(i.id), "check_code": i.check_code, "category": i.category,
             "severity": i.severity, "title": i.title, "url": i.url, "fix": i.fix,
             "seen_count": i.seen_count} for i in rows]


@router.get("/keywords")
def keywords(
    limit: int | None = _LIMIT, cursor: str | None = _CURSOR, db: Session = Depends(get_db),
) -> dict[str, object]:
    """Body is already an object, so the cluster page's cursor is a body field (`next_cursor`,
    `null` on the last page) rather than a header."""
    kws = db.execute(select(Keyword)).scalars().all()
    lim = effective_limit(limit, cursor)
    rows = db.execute(apply_keyset(
        select(KeywordCluster), (KeywordCluster.volume_sum, KeywordCluster.id),
        scope="keywords.clusters", cursor=cursor, limit=lim,
    )).scalars().all()
    clusters, next_cursor = finish_page(rows, scope="keywords.clusters", limit=lim,
                                        key_of=lambda c: (c.volume_sum, c.id))
    return {
        "count": len(kws),
        "clusters": [{"name": c.name, "size": c.size, "volume_sum": c.volume_sum,
                      "primary_intent": c.primary_intent, "intents": c.intents} for c in clusters],
        "next_cursor": next_cursor,
    }


@router.get("/anomalies")
def anomalies(
    request: Request, response: Response,
    project_id: uuid.UUID | None = Query(default=None),
    limit: int | None = _LIMIT, cursor: str | None = _CURSOR, db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(Anomaly).where(Anomaly.status == "open")
    if project_id is not None:
        q = q.where(Anomaly.project_id == project_id)
    rows = paginate(db, request, response, q, (Anomaly.detected_on, Anomaly.id),
                    scope="anomalies", cursor=cursor, limit=limit)
    return [{"id": str(a.id), "metric": a.metric, "direction": a.direction,
             "magnitude_pct": float(a.magnitude_pct), "detected_on": a.detected_on.isoformat(),
             "investigation": a.investigation} for a in rows]


@router.get("/experiments")
def experiments(
    request: Request, response: Response,
    project_id: uuid.UUID | None = Query(default=None),
    limit: int | None = _LIMIT, cursor: str | None = _CURSOR, db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(Experiment)
    if project_id is not None:
        q = q.where(Experiment.project_id == project_id)
    rows = paginate(db, request, response, q, (Experiment.created_at, Experiment.id),
                    scope="experiments", cursor=cursor, limit=limit)
    return [{"id": str(e.id), "type": e.experiment_type, "hypothesis": e.hypothesis,
             "state": e.state, "verdict": e.verdict,
             "confidence": float(e.confidence) if e.confidence is not None else None,
             "result": e.result, "confounders": e.confounders} for e in rows]


@router.get("/geo/visibility")
def geo_visibility(
    request: Request, response: Response,
    project_id: uuid.UUID | None = Query(default=None),
    limit: int | None = _LIMIT, cursor: str | None = _CURSOR, db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(AiVisibilityScore)
    if project_id is not None:
        q = q.where(AiVisibilityScore.project_id == project_id)
    rows = paginate(db, request, response, q, (AiVisibilityScore.week, AiVisibilityScore.id),
                    scope="geo.visibility", cursor=cursor, limit=limit)
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
