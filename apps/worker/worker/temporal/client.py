"""Thin client helpers for the durable autonomous-loop workflow (ADR-0003) — start it, signal an
approval/stop into a running instance, or query its status. Async, since `temporalio.client` is
async-only; call from an async context (a FastAPI route, or `asyncio.run` from a script)."""

from __future__ import annotations

from temporalio.client import Client, WorkflowHandle

from common.settings import settings
from worker.temporal.run_worker import TASK_QUEUE
from worker.temporal.workflows import (
    ApprovalSignal,
    LoopStatus,
    SeoAgentWorkflow,
    SeoAgentWorkflowParams,
)


async def _client() -> Client:
    if not settings.temporal_address:
        raise RuntimeError("TEMPORAL_ADDRESS not configured — see NEEDED-KEYS.md")
    kwargs: dict[str, object] = {"target_host": settings.temporal_address}
    if settings.temporal_namespace:
        kwargs["namespace"] = settings.temporal_namespace
    if settings.temporal_api_key:
        kwargs["api_key"] = settings.temporal_api_key
        kwargs["tls"] = True
    return await Client.connect(**kwargs)  # type: ignore[arg-type]


def workflow_id(tenant_id: str, project_id: str) -> str:
    return f"seo-agent-{tenant_id}-{project_id}"


async def start_autonomous_loop(
    tenant_id: str, project_id: str, *, goal: str | None = None, repo_path: str = ".",
) -> str:
    """Idempotent: starting an already-running workflow for this tenant/project is a no-op that
    returns the existing run's id (Temporal dedupes on workflow id by default)."""
    client = await _client()
    handle = await client.start_workflow(
        SeoAgentWorkflow.run,
        SeoAgentWorkflowParams(tenant_id=tenant_id, project_id=project_id, goal=goal,
                              repo_path=repo_path),
        id=workflow_id(tenant_id, project_id),
        task_queue=TASK_QUEUE,
    )
    return handle.result_run_id or handle.first_execution_run_id or ""


async def signal_approval(tenant_id: str, project_id: str, *, plan_id: str, decision: str) -> None:
    client = await _client()
    handle: WorkflowHandle[SeoAgentWorkflow, object] = client.get_workflow_handle(
        workflow_id(tenant_id, project_id)
    )
    await handle.signal(SeoAgentWorkflow.approve_plan, ApprovalSignal(plan_id=plan_id, decision=decision))


async def stop_autonomous_loop(tenant_id: str, project_id: str) -> None:
    client = await _client()
    handle: WorkflowHandle[SeoAgentWorkflow, object] = client.get_workflow_handle(
        workflow_id(tenant_id, project_id)
    )
    await handle.signal(SeoAgentWorkflow.stop)


async def query_status(tenant_id: str, project_id: str) -> LoopStatus:
    client = await _client()
    handle: WorkflowHandle[SeoAgentWorkflow, object] = client.get_workflow_handle(
        workflow_id(tenant_id, project_id)
    )
    return await handle.query(SeoAgentWorkflow.status)
