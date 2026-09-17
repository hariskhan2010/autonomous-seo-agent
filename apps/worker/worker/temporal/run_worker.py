"""Temporal worker entrypoint (A-TO-Z-PLAN.md §Phase 11, ADR-0003). Run with:

    uv run python -m worker.temporal.run_worker

Needs `TEMPORAL_ADDRESS` (self-hosted: `temporal server start-dev`, or Docker; plus
`TEMPORAL_NAMESPACE` + `TEMPORAL_API_KEY` for Temporal Cloud) — see NEEDED-KEYS.md. This process
is separate from the Celery worker (`worker.app`): Celery runs short unit jobs, this runs the
durable autonomous-loop workflow, whose activities call back into those same Celery job
functions directly (ADR-0003 — distinct, non-overlapping roles)."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from common.settings import settings
from worker.temporal.activities import detect_and_plan, execute_approved_plan
from worker.temporal.workflows import SeoAgentWorkflow

TASK_QUEUE = "seo-agent-autonomous"
log = logging.getLogger("worker.temporal")


async def main() -> None:
    if not settings.temporal_address:
        raise RuntimeError("TEMPORAL_ADDRESS not configured — see NEEDED-KEYS.md")

    connect_kwargs: dict[str, object] = {"target_host": settings.temporal_address}
    if settings.temporal_namespace:
        connect_kwargs["namespace"] = settings.temporal_namespace
    if settings.temporal_api_key:
        connect_kwargs["api_key"] = settings.temporal_api_key
        connect_kwargs["tls"] = True

    client = await Client.connect(**connect_kwargs)  # type: ignore[arg-type]

    # The wrapped jobs use blocking SQLAlchemy sessions, so activities are plain sync functions
    # run on a thread-pool executor rather than `async def` activities.
    with ThreadPoolExecutor(max_workers=10) as executor:
        worker = Worker(
            client, task_queue=TASK_QUEUE, workflows=[SeoAgentWorkflow],
            activities=[detect_and_plan, execute_approved_plan], activity_executor=executor,
        )
        log.info("starting Temporal worker on task queue %r", TASK_QUEUE)
        await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
