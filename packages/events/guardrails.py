"""Guardrails (A-TO-Z-PLAN.md §Phase 8, §49, §J).

Pre-transition / pre-apply checks. Any failing check blocks the action (raises `GuardrailBlock`)
— it never silently proceeds."""

from __future__ import annotations

from dataclasses import dataclass


class GuardrailBlock(RuntimeError):
    pass


@dataclass
class GuardContext:
    action_class: str
    approval_present: bool
    tenant_autonomous_types: set[str]
    opportunity_type: str
    pages_affected: int = 1
    loop_count: int = 0
    duplicate_action: bool = False
    mass_change_threshold: int = 50
    loop_cap: int = 25
    write_lease_held: bool = True


def check(ctx: GuardContext) -> None:
    if ctx.loop_count > ctx.loop_cap:
        raise GuardrailBlock(f"loop cap exceeded ({ctx.loop_count} > {ctx.loop_cap})")
    if ctx.duplicate_action:
        raise GuardrailBlock("duplicate-action hash: this exact change already applied")
    if not ctx.write_lease_held:
        raise GuardrailBlock("project write lease not held")

    if ctx.action_class in ("HIGH_RISK_WRITE", "IRREVERSIBLE_EXTERNAL_ACTION") and not ctx.approval_present:
        raise GuardrailBlock(f"{ctx.action_class} requires human approval")
    if ctx.action_class == "IRREVERSIBLE_EXTERNAL_ACTION":
        raise GuardrailBlock("IRREVERSIBLE_EXTERNAL_ACTION is never autonomous")
    if ctx.action_class == "LOW_RISK_WRITE" and not ctx.approval_present:
        if ctx.opportunity_type not in ctx.tenant_autonomous_types:
            raise GuardrailBlock(
                f"'{ctx.opportunity_type}' not on the tenant autonomous allow-list"
            )
    if ctx.pages_affected > ctx.mass_change_threshold and not ctx.approval_present:
        raise GuardrailBlock(
            f"mass-change guard: {ctx.pages_affected} pages > {ctx.mass_change_threshold} "
            "— explicit human approval required"
        )
