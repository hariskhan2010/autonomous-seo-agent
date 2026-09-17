"""`plan.build` + `plan.execute` worker jobs (A-TO-Z-PLAN.md §Phase 8).

plan.build:   opportunity → structured Plan + PlanStep rows + agent_decision (§Y).
plan.execute: approval check → guardrails → execution (conflict check + apply) →
              change_version → verification → (fail → rollback → incident).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable

import structlog

from db.models.events import OutboxEvent
from db.models.opportunity import Opportunity
from db.models.project import Project
from db.models.safety import (
    AgentDecision,
    Approval,
    Change,
    ChangeVersion,
    Incident,
    Plan,
    PlanStep,
    Rollback,
    Verification,
)
from db.session import tenant_session
from events.guardrails import GuardContext, GuardrailBlock
from events.guardrails import check as guardrail_check
from execution.adapters import ChangeSpec, get_adapter
from execution.approval import ApprovalPolicy, resolve
from execution.engine import ConflictError, apply_change
from planner import plan_for_opportunity
from rollback import execute_rollback
from seo_core.crawl.parser import parse_html
from seo_core.technical.models import PageView
from verification import verify_change

log = structlog.get_logger("job.planning")
UTC = dt.UTC


def build(tenant_id: str, project_id: str, opportunity_id: str,
          correlation_id: str | None = None) -> dict[str, object]:
    tid, pid, oid = uuid.UUID(tenant_id), uuid.UUID(project_id), uuid.UUID(opportunity_id)
    with tenant_session(tid, pid) as s:
        opp = s.get(Opportunity, oid)
        if opp is None:
            raise ValueError("opportunity not found")
        proj = s.get(Project, pid)
        auto_types = set((proj.config or {}).get("autonomous_types", [])) if proj else set()

        draft = plan_for_opportunity(
            {"id": str(oid), "type": opp.type, "url": opp.url, "url_pattern": opp.url_pattern,
             "title": opp.title, "recommendation": opp.recommendation,
             "verification_method": opp.verification_method,
             "proposed_change": opp.proposed_change},
            tenant_autonomous_types=auto_types,
        )

        decision = AgentDecision(
            tenant_id=tid, project_id=pid, kind="plan_chosen", agent="planner",
            agent_version="0.1.0", model_role=None,
            inputs={"opportunity_id": str(oid), "type": opp.type},
            output={"root_cause": draft.root_cause, "solution": draft.chosen_solution,
                    "unresolved": draft.unresolved},
            rationale=draft.root_cause, correlation_id=correlation_id,
        )
        s.add(decision)
        s.flush()

        plan = Plan(
            tenant_id=tid, project_id=pid, opportunity_id=oid,
            state="awaiting_approval" if draft.requires_approval else "approved",
            root_cause=draft.root_cause, chosen_solution=draft.chosen_solution,
            requires_approval=draft.requires_approval, max_action_class=draft.max_action_class,
            agent_decision_id=decision.id,
        )
        s.add(plan)
        s.flush()
        for step in draft.steps:
            s.add(PlanStep(
                tenant_id=tid, project_id=pid, plan_id=plan.id, ordinal=step.ordinal,
                objective=step.objective, tool=step.tool, tool_version=step.tool_version,
                inputs=step.inputs, preconditions=step.preconditions,
                expected_output=step.expected_output, action_class=step.action_class,
                permission=step.permission, verification=step.verification,
                rollback=step.rollback, depends_on=step.depends_on, timeout_s=step.timeout_s,
                retry_policy=step.retry_policy, idempotency_key=step.idempotency_key,
            ))
        opp.status = "planned" if not draft.unresolved else "analyzing"
        s.add(opp)
        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid,
            type="approval.required" if draft.requires_approval else "plan.ready",
            version=1, correlation_id=correlation_id,
            payload={"plan_id": str(plan.id), "opportunity_id": str(oid),
                     "steps": len(draft.steps), "unresolved": draft.unresolved},
        ))
        pid_out = str(plan.id)

    log.info("plan.built", plan_id=pid_out, steps=len(draft.steps), unresolved=draft.unresolved)
    return {"plan_id": pid_out, "steps": len(draft.steps), "requires_approval": draft.requires_approval,
            "unresolved": draft.unresolved}


def execute(tenant_id: str, project_id: str, plan_id: str, *, repo_path: str,
            fetch_live: Callable[[str], str] | None = None,
            correlation_id: str | None = None) -> dict[str, object]:
    """`fetch_live(url) -> html` is injected (the crawler in prod; a fixture in tests)."""
    tid, pid, plid = uuid.UUID(tenant_id), uuid.UUID(project_id), uuid.UUID(plan_id)
    now = dt.datetime.now(UTC)

    with tenant_session(tid, pid) as s:
        plan = s.get(Plan, plid)
        if plan is None:
            raise ValueError("plan not found")
        proj = s.get(Project, pid)
        policy = ApprovalPolicy(
            mode=(proj.approval_mode if proj else "assisted"),
            autonomous_types=set((proj.config or {}).get("autonomous_types", [])) if proj else set(),
        )
        opp = s.get(Opportunity, plan.opportunity_id)
        if opp is None:
            raise ValueError("opportunity for plan not found")
        opp_type = opp.type
        steps = s.query(PlanStep).filter(PlanStep.plan_id == plid).order_by(PlanStep.ordinal).all()
        approval = s.query(Approval).filter(Approval.plan_id == plid).first()
        approved = approval is not None and approval.decision in ("approved", "auto_approved")

        results: list[dict[str, object]] = []
        for step in steps:
            gate = resolve(policy, action_class=step.action_class, opportunity_type=opp_type)
            if gate == "blocked":
                results.append({"step": step.ordinal, "outcome": "blocked_read_only"})
                break
            if gate == "needs_human" and not approved:
                results.append({"step": step.ordinal, "outcome": "awaiting_approval"})
                break
            try:
                guardrail_check(GuardContext(
                    action_class=step.action_class, approval_present=approved,
                    tenant_autonomous_types=policy.autonomous_types, opportunity_type=opp_type,
                ))
            except GuardrailBlock as gb:
                results.append({"step": step.ordinal, "outcome": "guardrail_blocked", "reason": str(gb)})
                break

            change_id = uuid.uuid4()
            spec = ChangeSpec(
                op="write_file",
                path=str(step.inputs.get("target_path") or f"content{_url_path(str(step.inputs.get('url', '')))}.md"),
                new_content=str(step.inputs.get("new_content") or f"<!-- {step.objective} -->\n"),
                message=step.objective,
            )
            adapter = get_adapter("git_pr", repo_path=repo_path)
            plan_pre_hash = (step.expected_output or {}).get("pre_state_hash")
            try:
                outcome = apply_change(adapter, spec, change_id=change_id,
                                       plan_time_pre_hash=plan_pre_hash)
            except ConflictError as ce:
                results.append({"step": step.ordinal, "outcome": "conflict", "reason": str(ce)})
                break

            ch = Change(
                id=change_id, tenant_id=tid, project_id=pid, plan_id=plid, plan_step_id=step.id,
                adapter="git_pr", action_class=step.action_class, state="applied",
                target=spec.path, pre_state_hash=outcome.pre_state_hash,
                rollback_strategy=(step.rollback or {}).get("strategy", "native"),
                backup_ref=outcome.backup_ref, external_ref=outcome.external_ref,
                side_effect_key=step.idempotency_key, applied_at=now,
            )
            s.add(ch)
            s.add(ChangeVersion(tenant_id=tid, project_id=pid, change_id=change_id,
                                before={"content": outcome.before}, after={"content": outcome.after}))
            s.flush()

            # ── verification (immediate technical) ──
            verifier = (step.verification or {}).get("verifier", "metadata_change")
            passed, vdetail = _run_verification(verifier, step, spec, repo_path, fetch_live)
            s.add(Verification(tenant_id=tid, project_id=pid, change_id=change_id, kind="technical",
                               passed=passed, detail=vdetail, checked_at=dt.datetime.now(UTC)))
            ch.state = "verified" if passed else "failed"

            if not passed:
                rb = execute_rollback(adapter, spec, backup_ref=outcome.backup_ref,
                                      strategy=ch.rollback_strategy)
                s.add(Rollback(tenant_id=tid, project_id=pid, change_id=change_id,
                               strategy=rb.strategy, succeeded=rb.succeeded, verified=rb.succeeded,
                               detail=rb.detail, executed_at=dt.datetime.now(UTC)))
                ch.state = "rolled_back"
                s.add(Incident(tenant_id=tid, project_id=pid, change_id=change_id, severity="high",
                               title=f"Verification failed for step {step.ordinal} of plan {plid}",
                               detail={"verifier": verifier, **vdetail}))
                results.append({"step": step.ordinal, "outcome": "rolled_back",
                                "rollback_ok": rb.succeeded})
                break

            results.append({"step": step.ordinal, "outcome": "verified",
                            "external_ref": outcome.external_ref})

        plan.state = "done" if all(r["outcome"] == "verified" for r in results) and results else "failed"
        s.add(plan)
        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid,
            type="change.executed" if plan.state == "done" else "verification.failed",
            version=1, correlation_id=correlation_id,
            payload={"plan_id": plan_id, "results": results},
        ))

    log.info("plan.executed", plan_id=plan_id, results=results)
    return {"plan_id": plan_id, "results": results}


def _url_path(url: str) -> str:
    from urllib.parse import urlsplit
    return (urlsplit(url).path or "/index").rstrip("/") or "/index"


def _run_verification(verifier: str, step: object, spec: ChangeSpec, repo_path: str,
                      fetch_live: object) -> tuple[bool, dict[str, object]]:
    url = str(dict(getattr(step, "inputs", {}) or {}).get("url", ""))
    expect = dict(getattr(step, "verification", {}) or {})

    if callable(fetch_live):
        # production path: re-fetch the live public URL, parse, run the real verifier
        html = fetch_live(url)
        page = PageView.from_parsed(parse_html(html, url=url, final_url=url, http_status=200))
        res = verify_change(verifier, live_page=page, expect=expect)
        return res.passed, res.detail

    # offline path: the change landed if its content is present in the written file
    written = get_adapter("git_pr", repo_path=repo_path).read_state(spec) or ""
    landed = bool(spec.new_content.strip()) and spec.new_content in written
    return landed, {"mode": "offline_file_check", "landed": landed, "verifier": verifier}
