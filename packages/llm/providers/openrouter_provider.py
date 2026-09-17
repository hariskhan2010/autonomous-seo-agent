"""OpenRouter adapter (A-TO-Z-PLAN.md §H.3, ADR-0005) — OpenAI-compatible chat completions API,
one key routing to many model families (GLM, DeepSeek, Llama, `:free` variants, ...). This is what
lets `JUDGE` be a genuinely different model family from `WORKER` without a second paid provider
account — see `packages/llm/providers/gemini_provider.py`'s docstring for why this exists at all."""

from __future__ import annotations

import httpx

from common.settings import settings
from llm.provider import LLMResult, Message
from llm.registry import Binding

_API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterProvider:
    name = "openrouter"

    def complete(
        self, *, binding: Binding, system: str, messages: list[Message],
        max_tokens: int | None = None,
    ) -> LLMResult:
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")

        payload_messages = [{"role": "system", "content": system}] if system else []
        payload_messages += [{"role": m.role, "content": m.content} for m in messages]

        resp = httpx.post(
            f"{_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            json={
                "model": binding.model, "messages": payload_messages,
                "max_tokens": max_tokens or binding.max_output_tokens,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenRouter returned no choices: {data}")
        text = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        # OpenRouter reports actual spend directly — no per-model price table to maintain.
        cost_usd = float(usage.get("cost", 0.0) or 0.0)

        return LLMResult(
            text=text, input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)), model=binding.model,
            model_version=data.get("model", binding.model_version), provider=self.name,
            stop_reason=choices[0].get("finish_reason"), cost_usd=cost_usd,
        )

    def embed(self, *, binding: Binding, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "OpenRouter embeddings aren't wired up — EMBEDDING role uses a local model"
        )
