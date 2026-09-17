"""Real integration test for `SeoAgentWorkflow` against Temporal's time-skipping test server
(A-TO-Z-PLAN.md §Phase 11, ADR-0003) — not a mock: this is the actual Temporal Python SDK
sandbox/replay engine, just with a local, ephemeral, time-skipping server instead of a
production one. Activities are replaced with lightweight fakes so the test doesn't need a real
tenant/project/DB — the DB-backed activity bodies are exercised separately in
`tests/integration/test_orchestrator.py`-style tests, not here.

Signals sent right after `start_workflow` race the workflow's first task (there's no ordering
guarantee between a separate follow-up RPC and the workflow actually starting) — every test below
waits for an observable, workflow-driven condition (a query showing `passes >= 1`, or the fake
activity actually having run) before signalling, rather than sleeping a fixed guess."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from temporalio import activity
from temporalio.client import WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from worker.temporal.activities import DetectAndPlanInput, DetectAndPlanResult, ExecutePlanInput
from worker.temporal.workflows import (
    ApprovalSignal,
    LoopResult,
    SeoAgentWorkflow,
    SeoAgentWorkflowParams,
)

TASK_QUEUE = "test-seo-agent-autonomous"
WAIT_TIMEOUT_S = 10.0
_Handle = WorkflowHandle[SeoAgentWorkflow, LoopResult]


@pytest.fixture
async def env():
    try:
        async with await WorkflowEnvironment.start_time_skipping() as e:
            yield e
    except RuntimeError as exc:
        pytest.skip(f"Temporal time-skipping test server unavailable: {exc}")


async def _wait_for(predicate: Callable[[], Awaitable[bool]]) -> None:
    """Polls a zero-arg async predicate with real (not workflow-simulated) wall-clock waits."""
    async with asyncio.timeout(WAIT_TIMEOUT_S):
        while not await predicate():  # noqa: ASYNC110 - polling a remote query, no local Event to wait on
            await asyncio.sleep(0.02)


async def _passed(handle: _Handle, at_least: int) -> bool:
    status = await handle.query(SeoAgentWorkflow.status)
    return status.passes >= at_least


async def test_autonomous_plan_executes_without_waiting(env: WorkflowEnvironment) -> None:
    executed: list[str] = []

    @activity.defn(name="detect_and_plan")
    def fake_detect(inp: DetectAndPlanInput) -> DetectAndPlanResult:
        return DetectAndPlanResult(agent_run_id="run-1", autonomous_plan_ids=["plan-1"],
                                   awaiting_approval_plan_ids=[])

    @activity.defn(name="execute_approved_plan")
    def fake_execute(inp: ExecutePlanInput) -> dict[str, object]:
        executed.append(inp.plan_id)
        return {"plan_id": inp.plan_id, "results": []}

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[SeoAgentWorkflow],
        activities=[fake_detect, fake_execute],
        activity_executor=ThreadPoolExecutor(),
    ):
        handle = await env.client.start_workflow(
            SeoAgentWorkflow.run,
            SeoAgentWorkflowParams(tenant_id=str(uuid.uuid4()), project_id=str(uuid.uuid4()),
                                  max_passes_before_continue=1, idle_poll_interval_s=1),
            id=f"wf-{uuid.uuid4()}", task_queue=TASK_QUEUE,
        )
        # Don't signal stop until the autonomous plan has actually run — otherwise the signal can
        # race the workflow's very first task and short-circuit the loop before it does anything.
        async def _has_executed() -> bool:
            return bool(executed)

        await _wait_for(_has_executed)
        await handle.signal(SeoAgentWorkflow.stop)
        result = await handle.result()

    assert executed == ["plan-1"]
    assert result.stopped is True


async def test_waiting_plan_executes_only_after_approval_signal(env: WorkflowEnvironment) -> None:
    executed: list[str] = []

    @activity.defn(name="detect_and_plan")
    def fake_detect(inp: DetectAndPlanInput) -> DetectAndPlanResult:
        return DetectAndPlanResult(agent_run_id="run-1", autonomous_plan_ids=[],
                                   awaiting_approval_plan_ids=["plan-2"])

    @activity.defn(name="execute_approved_plan")
    def fake_execute(inp: ExecutePlanInput) -> dict[str, object]:
        executed.append(inp.plan_id)
        return {"plan_id": inp.plan_id, "results": []}

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[SeoAgentWorkflow],
        activities=[fake_detect, fake_execute],
        activity_executor=ThreadPoolExecutor(),
    ):
        handle = await env.client.start_workflow(
            SeoAgentWorkflow.run,
            SeoAgentWorkflowParams(tenant_id=str(uuid.uuid4()), project_id=str(uuid.uuid4()),
                                  max_passes_before_continue=5, idle_poll_interval_s=5),
            id=f"wf-{uuid.uuid4()}", task_queue=TASK_QUEUE,
        )
        # Wait until the workflow has actually detected the plan and is parked in wait_condition,
        # so the approval signal below can't race ahead of it existing.
        await _wait_for(lambda: _passed(handle, 1))
        assert executed == []  # nothing runs until approved

        await handle.signal(SeoAgentWorkflow.approve_plan,
                            ApprovalSignal(plan_id="plan-2", decision="approved"))
        await handle.signal(SeoAgentWorkflow.stop)
        result = await handle.result()

    assert executed == ["plan-2"]
    assert result.stopped is True


async def test_rejected_plan_is_never_executed(env: WorkflowEnvironment) -> None:
    executed: list[str] = []

    @activity.defn(name="detect_and_plan")
    def fake_detect(inp: DetectAndPlanInput) -> DetectAndPlanResult:
        return DetectAndPlanResult(agent_run_id="run-1", autonomous_plan_ids=[],
                                   awaiting_approval_plan_ids=["plan-3"])

    @activity.defn(name="execute_approved_plan")
    def fake_execute(inp: ExecutePlanInput) -> dict[str, object]:
        executed.append(inp.plan_id)
        return {"plan_id": inp.plan_id, "results": []}

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[SeoAgentWorkflow],
        activities=[fake_detect, fake_execute],
        activity_executor=ThreadPoolExecutor(),
    ):
        handle = await env.client.start_workflow(
            SeoAgentWorkflow.run,
            SeoAgentWorkflowParams(tenant_id=str(uuid.uuid4()), project_id=str(uuid.uuid4()),
                                  max_passes_before_continue=5, idle_poll_interval_s=5),
            id=f"wf-{uuid.uuid4()}", task_queue=TASK_QUEUE,
        )
        await _wait_for(lambda: _passed(handle, 1))
        await handle.signal(SeoAgentWorkflow.approve_plan,
                            ApprovalSignal(plan_id="plan-3", decision="rejected"))
        await handle.signal(SeoAgentWorkflow.stop)
        result = await handle.result()

    assert executed == []
    assert result.stopped is True


async def test_stop_signal_ends_the_loop_even_mid_run(env: WorkflowEnvironment) -> None:
    @activity.defn(name="detect_and_plan")
    def fake_detect(inp: DetectAndPlanInput) -> DetectAndPlanResult:
        return DetectAndPlanResult(agent_run_id="run-1", autonomous_plan_ids=[],
                                   awaiting_approval_plan_ids=[])

    @activity.defn(name="execute_approved_plan")
    def fake_execute(inp: ExecutePlanInput) -> dict[str, object]:
        raise AssertionError("should never be called — nothing to execute")

    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[SeoAgentWorkflow],
        activities=[fake_detect, fake_execute],
        activity_executor=ThreadPoolExecutor(),
    ):
        handle = await env.client.start_workflow(
            SeoAgentWorkflow.run,
            SeoAgentWorkflowParams(tenant_id=str(uuid.uuid4()), project_id=str(uuid.uuid4()),
                                  max_passes_before_continue=1000, idle_poll_interval_s=3600),
            id=f"wf-{uuid.uuid4()}", task_queue=TASK_QUEUE,
        )
        await _wait_for(lambda: _passed(handle, 1))
        await handle.signal(SeoAgentWorkflow.stop)
        result = await handle.result()

    assert result.stopped is True
    assert result.passes == 1


async def test_workflow_id_dedupes_concurrent_starts(env: WorkflowEnvironment) -> None:
    """Starting a workflow under an id that's already running should fail, not silently start a
    second instance — `client.start_autonomous_loop`'s idempotency depends on this."""
    @activity.defn(name="detect_and_plan")
    def fake_detect(inp: DetectAndPlanInput) -> DetectAndPlanResult:
        return DetectAndPlanResult(agent_run_id="run-1", autonomous_plan_ids=[],
                                   awaiting_approval_plan_ids=[])

    @activity.defn(name="execute_approved_plan")
    def fake_execute(inp: ExecutePlanInput) -> dict[str, object]:
        return {"plan_id": "x", "results": []}

    wf_id = f"wf-{uuid.uuid4()}"
    async with Worker(
        env.client, task_queue=TASK_QUEUE, workflows=[SeoAgentWorkflow],
        activities=[fake_detect, fake_execute],
        activity_executor=ThreadPoolExecutor(),
    ):
        params = SeoAgentWorkflowParams(tenant_id=str(uuid.uuid4()), project_id=str(uuid.uuid4()),
                                       max_passes_before_continue=1000, idle_poll_interval_s=3600)
        handle = await env.client.start_workflow(
            SeoAgentWorkflow.run, params, id=wf_id, task_queue=TASK_QUEUE,
        )
        with pytest.raises(WorkflowAlreadyStartedError):
            await env.client.start_workflow(
                SeoAgentWorkflow.run, params, id=wf_id, task_queue=TASK_QUEUE,
            )
        await handle.signal(SeoAgentWorkflow.stop)
        await handle.result()
