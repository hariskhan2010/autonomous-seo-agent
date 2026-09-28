"""Opportunity + plan + approval + change API — the minimal approval/ops console (§K.4).
A hard precondition for enabling any write mode. Full dashboard (Phase 12) supersedes it."""

from __future__ import annotations

import datetime as dt
import uuid

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import idempotency
from app.auth import Principal
from app.deps import get_db, require_role
from app.idempotency import IdempotencyKeyHeader
from app.pagination import MAX_LIMIT, paginate
from common.settings import settings
from db.models.evidence import Evidence, EvidenceLink
from db.models.opportunity import Opportunity
from db.models.safety import Approval, Change, Plan, PlanStep, Verification

router = APIRouter(tags=["approval-console"])
log = structlog.get_logger("api.approval")
UTC = dt.UTC

_CURSOR = Query(default=None, description="Opaque cursor from a previous `X-Next-Cursor` header.")
_LIMIT = Query(default=None, ge=1, le=MAX_LIMIT,
               description="Page size. Omit (with no cursor) for the full, unpaginated listing.")


async def _signal_temporal_after_commit(
    *, tenant_id: uuid.UUID, project_id: uuid.UUID, plan_id: uuid.UUID, decision: str,
) -> None:
    """Registered as a `BackgroundTasks` callback (see `approve_plan`), which FastAPI runs only
    after the response is sent — i.e. after `get_db`'s `tenant_session` has already committed the
    `Approval` row. Signalling before that commit would race a Temporal activity reading it back.

    Best-effort: if the durable autonomous loop (ADR-0003, `worker.temporal.SeoAgentWorkflow`) is
    running for this tenant/project, push the decision in as a signal so it acts immediately
    instead of waiting for its next idle-poll timeout. Not configured / not running / unreachable
    is fine — the `Approval` row is already the source of truth; whatever executes the plan
    (Celery `plan.execute`, or a Temporal activity) reads it independently of this signal."""
    if not settings.temporal_address:
        return
    try:
        from worker.temporal.client import signal_approval

        await signal_approval(str(tenant_id), str(project_id), plan_id=str(plan_id),
                              decision=decision)
    except Exception:  # noqa: BLE001 - best-effort; the Approval row already committed
        log.warning("temporal.signal_approval.failed", plan_id=str(plan_id),
                   tenant_id=str(tenant_id), project_id=str(project_id), exc_info=True)


@router.get("/opportunities")
def list_opportunities(
    request: Request, response: Response,
    project_id: uuid.UUID | None = Query(default=None),
    priority: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    limit: int | None = _LIMIT, cursor: str | None = _CURSOR,
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    """Highest score first. `?limit=&cursor=` pages it (next cursor in `X-Next-Cursor`)."""
    q = select(Opportunity)
    if project_id is not None:
        q = q.where(Opportunity.project_id == project_id)
    if priority:
        q = q.where(Opportunity.priority == priority)
    if status_:
        q = q.where(Opportunity.status == status_)
    rows = paginate(db, request, response, q, (Opportunity.score, Opportunity.id),
                    scope="opportunities", cursor=cursor, limit=limit)
    return [
        {
            "id": str(o.id), "type": o.type, "title": o.title, "url": o.url,
            "priority": o.priority, "score": float(o.score), "status": o.status,
            "action_class": o.action_class, "recommendation": o.recommendation,
            "expected_outcome": o.expected_outcome, "seen_count": o.seen_count,
        }
        for o in rows
    ]


@router.get("/opportunities/{opportunity_id}/evidence")
def opportunity_evidence(opportunity_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    links = db.execute(
        select(EvidenceLink).where(
            EvidenceLink.subject_type == "opportunity", EvidenceLink.subject_id == opportunity_id
        )
    ).scalars()
    out: list[dict[str, object]] = []
    for link in links:
        ev = db.get(Evidence, link.evidence_id)
        if ev:
            out.append({
                "evidence_id": str(ev.id), "kind": ev.kind, "source_url": ev.source_url,
                "provider": ev.provider, "content_hash": ev.content_hash,
                "confidence": float(ev.confidence) if ev.confidence is not None else None,
                "collected_at": ev.collected_at.isoformat(),
            })
    return out


@router.get("/opportunities/{opportunity_id}/plans")
def opportunity_plans(opportunity_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """The reverse lookup `Plan.opportunity_id` alone doesn't give you: found while building the
    dashboard, which needs to navigate from an opportunity to its plan(s) without already knowing
    a plan_id."""
    rows = db.execute(
        select(Plan).where(Plan.opportunity_id == opportunity_id).order_by(Plan.created_at.desc())
    ).scalars()
    return [
        {"id": str(p.id), "state": p.state, "requires_approval": p.requires_approval,
         "max_action_class": p.max_action_class, "created_at": p.created_at.isoformat()}
        for p in rows
    ]


@router.get("/plans/{plan_id}")
def get_plan(plan_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")
    steps = db.execute(
        select(PlanStep).where(PlanStep.plan_id == plan_id).order_by(PlanStep.ordinal)
    ).scalars()
    return {
        "id": str(plan.id), "opportunity_id": str(plan.opportunity_id), "state": plan.state,
        "root_cause": plan.root_cause, "chosen_solution": plan.chosen_solution,
        "requires_approval": plan.requires_approval, "max_action_class": plan.max_action_class,
        "steps": [
            {
                "ordinal": st.ordinal, "objective": st.objective, "tool": st.tool,
                "action_class": st.action_class, "permission": st.permission,
                "verification": st.verification, "rollback": st.rollback,
                "depends_on": st.depends_on,
            }
            for st in steps
        ],
    }


@router.post("/plans/{plan_id}/approve", status_code=status.HTTP_201_CREATED)
def approve_plan(
    plan_id: uuid.UUID,
    body: dict[str, object],
    background_tasks: BackgroundTasks,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
    principal: Principal = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Honors `Idempotency-Key`: a retried approval with the same key + body replays the first
    response (and does NOT re-signal Temporal or write a second `Approval` row)."""
    idem = idempotency.begin(db, response, tenant_id=principal.tenant_id, scope="plans.approve",
                             key=idempotency_key,
                             request={"plan_id": str(plan_id), "body": body})
    if idem.replayed:
        return dict(idem.body)
    result = _approve(plan_id, body, background_tasks, principal, db)
    idem.store(status.HTTP_201_CREATED, result)
    return result


def _approve(
    plan_id: uuid.UUID, body: dict[str, object], background_tasks: BackgroundTasks,
    principal: Principal, db: Session,
) -> dict[str, object]:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")
    decision = str(body.get("decision", "approved"))
    if decision not in ("approved", "rejected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be approved|rejected")
    if not body.get("note"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "a note is required")
    db.add(Approval(
        tenant_id=principal.tenant_id, project_id=plan.project_id, plan_id=plan_id,
        decision=decision, decided_by=principal.user_id, note=body["note"],
        decided_at=dt.datetime.now(UTC),
    ))
    plan.state = "approved" if decision == "approved" else "rejected"
    db.add(plan)
    background_tasks.add_task(
        _signal_temporal_after_commit, tenant_id=principal.tenant_id,
        project_id=plan.project_id, plan_id=plan_id, decision=decision,
    )
    return {"plan_id": str(plan_id), "decision": decision}


@router.get("/changes")
def list_changes(
    request: Request, response: Response,
    project_id: uuid.UUID | None = Query(default=None),
    limit: int | None = _LIMIT, cursor: str | None = _CURSOR, db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(Change)
    if project_id is not None:
        q = q.where(Change.project_id == project_id)
    rows = paginate(db, request, response, q, (Change.created_at, Change.id),
                    scope="changes", cursor=cursor, limit=limit)
    out: list[dict[str, object]] = []
    for c in rows:
        ver = db.execute(
            select(Verification).where(Verification.change_id == c.id)
        ).scalars().first()
        out.append({
            "id": str(c.id), "adapter": c.adapter, "state": c.state, "target": c.target,
            "action_class": c.action_class, "external_ref": c.external_ref,
            "rollback_strategy": c.rollback_strategy,
            "verified": bool(ver and ver.passed),
            "applied_at": c.applied_at.isoformat() if c.applied_at else None,
        })
    return out
