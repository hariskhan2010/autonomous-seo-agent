"""AI-answer provider abstraction (A-TO-Z-PLAN.md §Phase 10).

`query_ai_provider` unified tool sits on top of this. Each adapter returns the raw text + full
context. `FakeAiProvider` powers offline dev + citation-parser tests."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from common.settings import settings


@dataclass
class AiResult:
    text: str
    provider: str
    model: str
    model_version: str
    locale: str
    ran_at: dt.datetime
    raw: dict[str, object]


@runtime_checkable
class AiProvider(Protocol):
    name: str

    def ask(self, prompt: str, *, locale: str = "en-US") -> AiResult: ...


def get_ai_provider(name: str) -> AiProvider:
    keyed = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "perplexity": settings.perplexity_api_key,
        "openrouter": settings.openrouter_api_key,
    }
    if not keyed.get(name):
        raise RuntimeError(f"{name} AI provider not configured — see NEEDED-KEYS.md")
    from integrations.ai_providers.openai_compatible import OpenAiCompatibleProvider

    return OpenAiCompatibleProvider(name)
