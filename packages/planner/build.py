"""Structured planner (A-TO-Z-PLAN.md §Phase 8).

Opportunity → root cause → chosen solution → an ordered `StepDraft` DAG. Each step declares
tool + inputs + preconditions + expected output + action class + permission + verification +
rollback + timeout + retry + dependencies + idempotency key.

For the mapped issue types the plan is fully deterministic. `STRATEGY`-role reasoning fills the
root-cause / solution rationale and any novel opportunity types (recorded as an agent_decision)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# opportunity.type -> (tool, action_class, rollback_strategy, verifier, objective template)
_RECIPES: dict[str, tuple[str, str, str, str, str]] = {
    "fix_canonical": (
        "modify_metadata", "LOW_RISK_WRITE", "native", "canonical_change",
        "Set a self-referencing canonical on {url}",
    ),
    "fix_technical_issue": (
        "modify_metadata", "LOW_RISK_WRITE", "native", "metadata_change",
        "Correct the flagged element on {url}",
    ),
    "add_schema": (
        "modify_metadata", "LOW_RISK_WRITE", "native", "schema_change",
        "Add valid JSON-LD schema to {url}",
    ),
    "add_internal_links": (
        "modify_metadata", "LOW_RISK_WRITE", "native", "internal_link_added",
        "Add a contextual internal link to {url}",
    ),
    "improve_thin_content": (
        "create_content", "HIGH_RISK_WRITE", "native", "content_change",
        "Expand thin content on {url}",
    ),
    "consolidate_cannibalization": (
        "update_cms", "HIGH_RISK_WRITE", "compensating", "redirect_added",
        "Consolidate competing pages for {url_pattern} and 301 the duplicates",
    ),
}

# change types the tenant may run autonomously once eval clears (A-TO-Z-PLAN.md §K.1).
# Ceiling only — a type still needs the tenant's own opt-in (Project.config.autonomous_types)
# AND action_class == LOW_RISK_WRITE (enforced below) before it can skip approval. Every member
# here must have rollback_strategy == "native" in _RECIPES — never widen this to a HIGH_RISK_WRITE
# or non-native-rollback type; that boundary is enforced again, independently, in
# execution.approval.resolve and events.guardrails.check (defense in depth).
_AUTONOMOUS_ALLOWLIST = {"fix_canonical", "add_schema", "fix_technical_issue", "add_internal_links"}


@dataclass
class StepDraft:
    ordinal: int
    objective: str
    tool: str
    tool_version: str
    inputs: dict[str, object]
    preconditions: list[str]
    expected_output: dict[str, object]
    action_class: str
    permission: str
    verification: dict[str, object]
    rollback: dict[str, object]
    depends_on: list[int]
    timeout_s: int
    retry_policy: dict[str, object]
    idempotency_key: str


@dataclass
class PlanDraft:
    opportunity_id: str
    root_cause: str
    chosen_solution: str
    requires_approval: bool
    max_action_class: str
    steps: list[StepDraft] = field(default_factory=list)
    unresolved: str | None = None  # set when the planner can't build a deterministic plan


def _idem(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:40]


def plan_for_opportunity(opp: dict[str, object], *, tenant_autonomous_types: set[str] | None = None) -> PlanDraft:
    otype = str(opp["type"])
    oid = str(opp["id"])
    url = str(opp.get("url") or "")
    pattern = str(opp.get("url_pattern") or "")
    allow = (tenant_autonomous_types or set()) & _AUTONOMOUS_ALLOWLIST

    recipe = _RECIPES.get(otype)
    if recipe is None:
        return PlanDraft(
            opportunity_id=oid, root_cause="unknown (no deterministic recipe)",
            chosen_solution="", requires_approval=True, max_action_class="HIGH_RISK_WRITE",
            unresolved=f"no recipe for opportunity type {otype!r}; needs STRATEGY-role planning",
        )

    tool, action_class, rollback_strategy, verifier, objective_tpl = recipe
    autonomous_ok = otype in allow and action_class == "LOW_RISK_WRITE"
    permission = "auto" if autonomous_ok else "approval_required"

    step = StepDraft(
        ordinal=1,
        objective=objective_tpl.format(url=url or pattern, url_pattern=pattern or url),
        tool=tool,
        tool_version="0.1.0",
        inputs={"url": url, "url_pattern": pattern, "change": opp.get("proposed_change", {})},
        preconditions=[f"live state of {url or pattern} matches the plan-time snapshot hash"],
        expected_output={"applied": True, "verifier": verifier},
        action_class=action_class,
        permission=permission,
        verification={"verifier": verifier, "assert": str(opp.get("verification_method") or "re-check the element")},
        rollback={"strategy": rollback_strategy, "note": "revert the change / close the PR"},
        depends_on=[],
        timeout_s=120,
        retry_policy={"max_attempts": 2, "backoff_s": 5},
        idempotency_key=_idem("step", oid, tool, url or pattern),
    )
    return PlanDraft(
        opportunity_id=oid,
        root_cause=f"{otype}: {opp.get('title', '')}",
        chosen_solution=str(opp.get("recommendation") or objective_tpl),
        requires_approval=not autonomous_ok,
        max_action_class=action_class,
        steps=[step],
    )
