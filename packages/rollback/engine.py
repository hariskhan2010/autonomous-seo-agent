"""Rollback engine (A-TO-Z-PLAN.md §Phase 8, §K.2).

Verification failed → execute the declared rollback strategy → (caller re-verifies) → open an
incident. A change whose strategy is `none` (IRREVERSIBLE_EXTERNAL_ACTION) never reaches here —
it can't run in assisted-auto / autonomous mode."""

from __future__ import annotations

from dataclasses import dataclass, field

from execution.adapters import ChangeAdapter, ChangeSpec


@dataclass
class RollbackResult:
    strategy: str
    succeeded: bool
    detail: dict[str, object] = field(default_factory=dict)


def execute_rollback(
    adapter: ChangeAdapter,
    spec: ChangeSpec,
    *,
    backup_ref: str | None,
    strategy: str,
) -> RollbackResult:
    if strategy in ("none", "manual"):
        return RollbackResult(strategy=strategy, succeeded=False,
                              detail={"note": "no automatic rollback; manual recovery runbook"})
    try:
        ok = adapter.rollback(spec, backup_ref=backup_ref)
    except Exception as exc:  # noqa: BLE001
        return RollbackResult(strategy=strategy, succeeded=False, detail={"error": str(exc)})
    return RollbackResult(strategy=strategy, succeeded=ok,
                          detail={"backup_ref": backup_ref, "adapter": adapter.name})
