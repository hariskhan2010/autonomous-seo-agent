from __future__ import annotations

from planner import plan_for_opportunity


def _opp(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "opp-1", "type": "fix_canonical", "url": "https://x.com/a",
        "url_pattern": None, "title": "Canonical points elsewhere",
        "recommendation": "self-canonical", "verification_method": "assert canonical == url",
        "proposed_change": {"canonical": "https://x.com/a"},
    }
    base.update(kw)
    return base


def test_low_risk_recipe_builds_structured_step() -> None:
    plan = plan_for_opportunity(_opp())
    assert plan.unresolved is None
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.tool == "modify_metadata"
    assert step.action_class == "LOW_RISK_WRITE"
    assert step.verification["verifier"] == "canonical_change"
    assert step.rollback["strategy"] == "native"
    assert step.idempotency_key
    assert plan.requires_approval is True  # not on the tenant's autonomous list


def test_autonomous_allowlisted_type_skips_approval() -> None:
    plan = plan_for_opportunity(_opp(type="add_schema"), tenant_autonomous_types={"add_schema"})
    assert plan.requires_approval is False
    assert plan.steps[0].permission == "auto"


def test_newly_widened_allowlist_types_skip_approval_when_tenant_opts_in() -> None:
    for otype in ("fix_technical_issue", "add_internal_links"):
        plan = plan_for_opportunity(_opp(type=otype), tenant_autonomous_types={otype})
        assert plan.requires_approval is False, otype
        assert plan.steps[0].permission == "auto", otype
        assert plan.steps[0].action_class == "LOW_RISK_WRITE", otype


def test_allowlisted_type_still_requires_approval_without_tenant_opt_in() -> None:
    # widening the ceiling doesn't auto-enroll every tenant — they must still opt in.
    plan = plan_for_opportunity(_opp(type="add_internal_links"), tenant_autonomous_types=set())
    assert plan.requires_approval is True
    assert plan.steps[0].permission == "approval_required"


def test_high_risk_type_always_requires_approval() -> None:
    plan = plan_for_opportunity(_opp(type="improve_thin_content"),
                                tenant_autonomous_types={"improve_thin_content"})
    assert plan.requires_approval is True
    assert plan.steps[0].action_class == "HIGH_RISK_WRITE"


def test_unknown_type_is_unresolved_for_strategy_planning() -> None:
    plan = plan_for_opportunity(_opp(type="brand_new_kind"))
    assert plan.unresolved is not None
    assert not plan.steps
    assert plan.requires_approval is True
