"""Provider abstraction (A-TO-Z-PLAN.md §H.3). One interface; adapters slot in without touching
call sites. Phase 1 ships the interface + an Anthropic adapter; other providers land per phase."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from llm.registry import Binding


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    model_version: str
    provider: str
    stop_reason: str | None = None
    used_fallback: bool = False
    cost_usd: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(
        self,
        *,
        binding: Binding,
        system: str,
        messages: list[Message],
        max_tokens: int | None = None,
    ) -> LLMResult: ...

    def embed(self, *, binding: Binding, texts: list[str]) -> list[list[float]]: ...
