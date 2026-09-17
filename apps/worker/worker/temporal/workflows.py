"""The durable autonomous-loop workflow (A-TO-Z-PLAN.md §Phase 11, ADR-0003).

This is the production Orchestrator ADR-0003 calls for: survives multi-day waits, worker
crashes, and deploys (Temporal replays its event history); waits at human-approval gates via
signals instead of polling a DB column; per-activity timeouts + retries. The one-shot Celery
`orchestrator.run_once` job still exists for a single manual/ad-hoc pass — this workflow is the
always-on loop, and calls the exact same jobs as activities (see `activities.py`).

Workflow code must stay deterministic: no direct I/O, no `datetime.now()`, no random — every
side effect goes through `workflow.execute_activity`."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from worker.temporal.activities import (
        DetectAndPlanInput,
        DetectAndPlanResult,
        ExecutePlanInput,
        detect_and_plan,
        execute_approved_plan,
    )

DEFAULT_ACTIVITY_TIMEOUT = dt.timedelta(minutes=10)
DETECT_RETRY = RetryPolicy(maximum_attempts=3)
EXECUTE_RETRY = RetryPolicy(maximum_attempts=2)


@dataclass
class SeoAgentWorkflowParams:
    tenant_id: str
    project_id: str
    goal: str | None = None
    repo_path: str = "."
    max_passes_before_continue: int = 20   # Temporal history-reset cadence, not a hard stop
    idle_poll_interval_s: int = 3600


@dataclass
class ApprovalSignal:
    plan_id: str
    decision: str   # "approved" | "rejected"


@dataclass
class LoopStatus:
    passes: int
    pending_decisions: dict[str, str]
    stop_requested: bool


@dataclass
class LoopResult:
    passes: int
    stopped: bool


@workflow.defn
class SeoAgentWorkflow:
    """OBSERVE → PLAN → (auto-execute | wait for a human) → LEARN, looping until `stop()` is
    signalled. History is reset via `continue_as_new` every `max_passes_before_continue` passes
    so a long-lived loop doesn't grow an unbounded event history."""

    def __init__(self) -> None:
        self._decisions: dict[str, str] = {}
        self._stop_requested = False
        self._passes = 0

    @workflow.signal
    def approve_plan(self, signal: ApprovalSignal) -> None:
        self._decisions[signal.plan_id] = signal.decision

    @workflow.signal
    def stop(self) -> None:
        self._stop_requested = True

    @workflow.query
    def status(self) -> LoopStatus:
        return LoopStatus(passes=self._passes, pending_decisions=dict(self._decisions),
                          stop_requested=self._stop_requested)

    @workflow.run
    async def run(self, params: SeoAgentWorkflowParams) -> LoopResult:
        while not self._stop_requested:
            self._passes += 1
            detect: DetectAndPlanResult = await workflow.execute_activity(
                detect_and_plan,
                DetectAndPlanInput(tenant_id=params.tenant_id, project_id=params.project_id,
                                  goal=params.goal),
                start_to_close_timeout=DEFAULT_ACTIVITY_TIMEOUT, retry_policy=DETECT_RETRY,
            )

            for plan_id in detect.autonomous_plan_ids:
                await workflow.execute_activity(
                    execute_approved_plan,
                    ExecutePlanInput(tenant_id=params.tenant_id, project_id=params.project_id,
                                     plan_id=plan_id, repo_path=params.repo_path),
                    start_to_close_timeout=DEFAULT_ACTIVITY_TIMEOUT, retry_policy=EXECUTE_RETRY,
                )

            waiting = list(detect.awaiting_approval_plan_ids)
            if waiting:
                def _still_waiting(waiting: list[str] = waiting) -> bool:
                    return self._stop_requested or any(p in self._decisions for p in waiting)

                # durable wait: Temporal parks the workflow, no polling loop burning compute.
                await workflow.wait_condition(
                    _still_waiting, timeout=dt.timedelta(seconds=params.idle_poll_interval_s),
                )
                for plan_id in [p for p in waiting if p in self._decisions]:
                    decision = self._decisions.pop(plan_id)
                    if decision == "approved":
                        await workflow.execute_activity(
                            execute_approved_plan,
                            ExecutePlanInput(tenant_id=params.tenant_id,
                                            project_id=params.project_id, plan_id=plan_id,
                                            repo_path=params.repo_path),
                            start_to_close_timeout=DEFAULT_ACTIVITY_TIMEOUT,
                            retry_policy=EXECUTE_RETRY,
                        )
            elif not self._stop_requested:
                await workflow.sleep(dt.timedelta(seconds=params.idle_poll_interval_s))

            if self._passes >= params.max_passes_before_continue and not self._stop_requested:
                workflow.continue_as_new(params)

        return LoopResult(passes=self._passes, stopped=True)
