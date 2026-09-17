"""LLM cost meter (A-TO-Z-PLAN.md §L, §Phase 1 deferral now wired).

Persists every LLM call as a `tool_calls` row (tool='llm.<role>') carrying role / provider /
model / model_version / tokens / cost. Best-effort — a metering failure never breaks a call."""

from __future__ import annotations

import uuid

import structlog

from llm.provider import LLMResult
from llm.roles import Role

log = structlog.get_logger("llm.meter")


def record_call(
    result: LLMResult,
    *,
    role: Role,
    tenant_id: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
    caller: str = "system",
    correlation_id: str | None = None,
    agent_run_id: uuid.UUID | None = None,
) -> None:
    if tenant_id is None:
        return  # no tenant context (e.g. an offline analyzer) → skip persistence, structlog only
    try:
        from db.models.crawl import ToolCall
        from db.session import tenant_session

        with tenant_session(tenant_id, project_id) as s:
            s.add(ToolCall(
                tenant_id=tenant_id, project_id=project_id, agent_run_id=agent_run_id,
                correlation_id=correlation_id, tool=f"llm.{role.value.lower()}",
                tool_version="0.1.0", caller=caller, risk="READ_ONLY", outcome="ok",
                llm_role=role.value, llm_provider=result.provider, llm_model=result.model,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
            ))
    except Exception:  # noqa: BLE001
        log.exception("llm.meter.persist_failed", role=role, provider=result.provider)
