"""Tool registry (A-TO-Z-PLAN.md §I, TOOLS.md).

The ONLY way an agent touches the world. Every tool has a typed descriptor; every call is
schema-validated in and out, risk-gated, and written to `tool_calls` (audit + cost meter).
Agents have no raw shell / db / fs / network — those primitives are not exposed here."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError

log = structlog.get_logger("tools")


class Risk(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW_RISK_WRITE = "LOW_RISK_WRITE"
    HIGH_RISK_WRITE = "HIGH_RISK_WRITE"
    IRREVERSIBLE_EXTERNAL_ACTION = "IRREVERSIBLE_EXTERNAL_ACTION"


class ToolError(RuntimeError):
    pass


class ToolPermissionError(ToolError):
    pass


@dataclass(frozen=True)
class ToolContext:
    tenant_id: uuid.UUID
    project_id: uuid.UUID | None = None
    caller: str = "system"          # agent name, or "system"
    correlation_id: str | None = None
    agent_run_id: uuid.UUID | None = None
    allowed_hosts: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    risk: Risk
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], BaseModel]
    allowed_agents: frozenset[str] = field(default_factory=frozenset)  # empty = any
    scope: str = "project"          # "project" | "tenant"
    timeout_s: float = 30.0
    permission: str = "auto"        # "auto" | "approval_required"


_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    if spec.name in _REGISTRY:
        raise ValueError(f"tool {spec.name!r} already registered")
    if spec.risk in (Risk.HIGH_RISK_WRITE, Risk.IRREVERSIBLE_EXTERNAL_ACTION):
        object.__setattr__(spec, "permission", "approval_required")
    _REGISTRY[spec.name] = spec


def get(name: str) -> ToolSpec:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise ToolError(f"no such tool: {name!r}") from exc


def all_specs() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def _persist_call(spec: ToolSpec, ctx: ToolContext, *, outcome: str, latency_ms: int,
                  inputs_hash: str, error: str | None) -> None:
    """Write the audit row. Import here to keep the registry importable without a DB."""
    try:
        from db.models.crawl import ToolCall
        from db.session import tenant_session

        with tenant_session(ctx.tenant_id, ctx.project_id) as s:
            s.add(ToolCall(
                tenant_id=ctx.tenant_id, project_id=ctx.project_id, agent_run_id=ctx.agent_run_id,
                correlation_id=ctx.correlation_id, tool=spec.name, tool_version=spec.version,
                caller=ctx.caller, risk=str(spec.risk), inputs_hash=inputs_hash,
                outcome=outcome, latency_ms=latency_ms, error=error,
            ))
    except Exception:  # noqa: BLE001 - auditing must never break a tool call; log and move on
        log.exception("tool_call.audit_failed", tool=spec.name)


def invoke(name: str, payload: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    spec = get(name)
    if spec.allowed_agents and ctx.caller not in spec.allowed_agents:
        _persist_call(spec, ctx, outcome="blocked", latency_ms=0, inputs_hash="", error="caller not allowed")
        raise ToolPermissionError(f"{ctx.caller!r} may not call {name!r}")
    if spec.scope == "project" and ctx.project_id is None:
        raise ToolError(f"{name!r} is project-scoped but no project_id in context")

    inputs_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    try:
        args = spec.input_model.model_validate(payload)
    except ValidationError as exc:
        _persist_call(spec, ctx, outcome="error", latency_ms=0, inputs_hash=inputs_hash, error=str(exc))
        raise ToolError(f"invalid input for {name!r}: {exc}") from exc

    started = time.monotonic()
    try:
        result = spec.handler(args, ctx)
        validated = spec.output_model.model_validate(result, from_attributes=True)
        latency_ms = int((time.monotonic() - started) * 1000)
        _persist_call(spec, ctx, outcome="ok", latency_ms=latency_ms, inputs_hash=inputs_hash, error=None)
        return validated.model_dump()
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        _persist_call(spec, ctx, outcome="error", latency_ms=latency_ms, inputs_hash=inputs_hash, error=str(exc))
        raise
