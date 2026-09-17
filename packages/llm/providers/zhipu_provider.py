"""Zhipu / GLM adapter (A-TO-Z-PLAN.md §H.3, ADR-0005) — OpenAI-compatible chat completions API.
See `gemini_provider.py`'s docstring for why this and the other free-tier adapters exist.

Model naming note, found while wiring up a real key: the older `glm-4-flash` name this project's
docs originally referenced returns "model does not exist" against the current API — the free
flash-tier model is now `glm-4.5-flash`."""

from __future__ import annotations

import httpx

from common.settings import settings
from llm.provider import LLMResult, Message
from llm.registry import Binding

_API_BASE = "https://open.bigmodel.cn/api/paas/v4"


class ZhipuProvider:
    name = "zhipu"

    def complete(
        self, *, binding: Binding, system: str, messages: list[Message],
        max_tokens: int | None = None,
    ) -> LLMResult:
        if not settings.zhipu_api_key:
            raise RuntimeError("ZHIPU_API_KEY is not set")

        payload_messages = [{"role": "system", "content": system}] if system else []
        payload_messages += [{"role": m.role, "content": m.content} for m in messages]

        resp = httpx.post(
            f"{_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {settings.zhipu_api_key}"},
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
            raise RuntimeError(f"Zhipu returned no choices: {data}")
        text = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})

        return LLMResult(
            text=text, input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)), model=binding.model,
            model_version=binding.model_version, provider=self.name,
            stop_reason=choices[0].get("finish_reason"), cost_usd=0.0,
        )

    def embed(self, *, binding: Binding, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Zhipu embeddings aren't wired up — EMBEDDING role uses a local model"
        )
