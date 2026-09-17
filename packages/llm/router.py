"""Role-based router (A-TO-Z-PLAN.md §H.3, §L).

Responsibilities:
- Resolve a Role -> Binding via the registry.
- **Redaction gate**: no secret string may leave the process in a prompt (§52). `assert_clean`
  raises before any provider call.
- Walk the fallback chain on provider error.
- Return an LLMResult carrying model/version/provider/tokens/cost for the caller to persist into
  `tool_calls` / `agent_decisions` (§Y). Structured-output validation + budgets land next.
"""

from __future__ import annotations

import json
from typing import TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from common.redaction import assert_clean, redact
from common.settings import settings
from llm.provider import LLMProvider, LLMResult, Message
from llm.registry import get_registry
from llm.roles import Role

log = structlog.get_logger("llm.router")

TModel = TypeVar("TModel", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass

_PROVIDERS: dict[str, LLMProvider] = {}


def _provider(name: str) -> LLMProvider:
    if name not in _PROVIDERS:
        if name == "anthropic":
            from llm.providers.anthropic_provider import AnthropicProvider

            _PROVIDERS[name] = AnthropicProvider()
        elif name == "gemini":
            from llm.providers.gemini_provider import GeminiProvider

            _PROVIDERS[name] = GeminiProvider()
        elif name == "openrouter":
            from llm.providers.openrouter_provider import OpenRouterProvider

            _PROVIDERS[name] = OpenRouterProvider()
        elif name == "zhipu":
            from llm.providers.zhipu_provider import ZhipuProvider

            _PROVIDERS[name] = ZhipuProvider()
        else:
            raise RuntimeError(f"No provider adapter registered for {name!r}")
    return _PROVIDERS[name]


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def complete(
    role: Role,
    *,
    system: str,
    messages: list[Message],
    max_tokens: int | None = None,
    tenant_id: object | None = None,
    project_id: object | None = None,
    caller: str = "system",
    correlation_id: str | None = None,
) -> LLMResult:
    secrets = settings.secret_values()
    assert_clean(system, secrets)
    for m in messages:
        assert_clean(m.content, secrets)

    registry = get_registry()

    # Per-call input budget (A-TO-Z-PLAN.md §L). Full per-run/per-tenant ceilings land with the
    # cost meter + `tool_calls` persistence.
    cap = int(registry.budgets.get("per_call_input_tokens", 0) or 0)
    if cap:
        est = _approx_tokens(system) + sum(_approx_tokens(m.content) for m in messages)
        if est > cap:
            raise BudgetExceeded(f"estimated input {est} tok exceeds per_call cap {cap}")

    chain = registry.fallback_chain(role)
    last_exc: Exception | None = None
    for i, binding in enumerate(chain):
        try:
            result = _provider(binding.provider).complete(
                binding=binding, system=system, messages=messages, max_tokens=max_tokens
            )
            result.used_fallback = i > 0
            log.info(
                "llm.complete",
                role=role,
                provider=binding.provider,
                model=binding.model,
                model_version=result.model_version,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                used_fallback=result.used_fallback,
            )
            if tenant_id is not None:
                import uuid as _uuid

                from llm.meter import record_call

                record_call(
                    result, role=role,
                    tenant_id=_uuid.UUID(str(tenant_id)),
                    project_id=_uuid.UUID(str(project_id)) if project_id is not None else None,
                    caller=caller, correlation_id=correlation_id,
                )
            return result
        except Exception as exc:  # noqa: BLE001 - deliberately broad; walk the chain
            last_exc = exc
            log.warning(
                "llm.fallback",
                role=role,
                failed_provider=binding.provider,
                error=redact(str(exc), secrets),
            )
    raise RuntimeError(f"All providers failed for role {role}") from last_exc


def complete_structured(  # noqa: UP047 - explicit TypeVar reads clearer here
    role: Role,
    *,
    system: str,
    messages: list[Message],
    schema: type[TModel],
    max_tokens: int | None = None,
    tenant_id: object | None = None,
    project_id: object | None = None,
    caller: str = "system",
    correlation_id: str | None = None,
) -> tuple[TModel, LLMResult]:
    """Structured output (A-TO-Z-PLAN.md §H.3): validate against `schema`; one repair retry with
    the error appended; then fail the step. Never returns unvalidated JSON."""
    instruction = (
        f"{system}\n\nRespond with ONLY a JSON object matching this schema:\n"
        f"{json.dumps(schema.model_json_schema())}"
    )
    result = complete(role, system=instruction, messages=messages, max_tokens=max_tokens,
                      tenant_id=tenant_id, project_id=project_id, caller=caller,
                      correlation_id=correlation_id)
    for attempt in range(2):
        try:
            return schema.model_validate_json(_extract_json(result.text)), result
        except (ValidationError, ValueError) as exc:
            if attempt == 1:
                raise
            repair = [*messages, Message("assistant", result.text),
                      Message("user", f"That failed validation: {exc}. Return only valid JSON.")]
            result = complete(role, system=instruction, messages=repair, max_tokens=max_tokens,
                              tenant_id=tenant_id, project_id=project_id, caller=caller,
                              correlation_id=correlation_id)
    raise AssertionError("unreachable")


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return text[start : end + 1]
