"""Execution engine (A-TO-Z-PLAN.md §Phase 8, §K.3).

Flow: preview → conflict check → backup → apply → record change_version.
Conflict check: the live pre-state hash must match the hash captured at plan time — no blind
overwrites. Idempotent apply via `side_effect_key`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from execution.adapters import ChangeAdapter, ChangeSpec


class ExecutionError(RuntimeError):
    pass


class ConflictError(ExecutionError):
    pass


@dataclass
class ExecutionOutcome:
    change_id: uuid.UUID
    external_ref: str | None
    backup_ref: str | None
    before: str
    after: str
    pre_state_hash: str | None
    after_state_hash: str | None


def preview_change(adapter: ChangeAdapter, spec: ChangeSpec) -> str:
    return adapter.preview(spec).diff


def apply_change(
    adapter: ChangeAdapter,
    spec: ChangeSpec,
    *,
    change_id: uuid.UUID,
    plan_time_pre_hash: str | None,
) -> ExecutionOutcome:
    before = adapter.read_state(spec) or ""
    preview = adapter.preview(spec)

    # ── conflict detection (§Phase 8) ──
    if plan_time_pre_hash is not None and preview.pre_state_hash != plan_time_pre_hash:
        raise ConflictError(
            f"live state drifted since planning "
            f"(plan={plan_time_pre_hash[:12]}, live={(preview.pre_state_hash or 'none')[:12]}) — aborting"
        )

    if not preview.would_change:
        # already in the desired state → idempotent no-op
        return ExecutionOutcome(
            change_id=change_id, external_ref=None, backup_ref=None,
            before=before, after=before,
            pre_state_hash=preview.pre_state_hash, after_state_hash=preview.pre_state_hash,
        )

    result = adapter.apply(spec)
    after = adapter.read_state(spec) or ""
    return ExecutionOutcome(
        change_id=change_id, external_ref=result.external_ref, backup_ref=result.backup_ref,
        before=before, after=after,
        pre_state_hash=preview.pre_state_hash, after_state_hash=result.after_state_hash,
    )
