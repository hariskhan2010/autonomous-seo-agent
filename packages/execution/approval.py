"""Approval-mode resolution (A-TO-Z-PLAN.md §K).

Per tenant/project + per change class. `read_only` blocks all writes; `assisted` (default)
requires a human approval row; `autonomous` auto-approves only allowlisted LOW_RISK_WRITE types
whose owning agent's eval is above threshold."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ApprovalPolicy:
    mode: str = "assisted"                       # read_only | assisted | autonomous
    autonomous_types: set[str] = field(default_factory=set)
    agent_eval_ok: bool = True


def resolve(policy: ApprovalPolicy, *, action_class: str, opportunity_type: str) -> str:
    """Returns: 'blocked' | 'needs_human' | 'auto'."""
    if action_class == "READ_ONLY":
        return "auto"
    if policy.mode == "read_only":
        return "blocked"
    if action_class in ("HIGH_RISK_WRITE", "IRREVERSIBLE_EXTERNAL_ACTION"):
        return "needs_human"
    if policy.mode == "autonomous" and action_class == "LOW_RISK_WRITE":
        if opportunity_type in policy.autonomous_types and policy.agent_eval_ok:
            return "auto"
    return "needs_human"
