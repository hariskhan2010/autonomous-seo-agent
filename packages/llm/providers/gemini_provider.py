"""Google Gemini adapter (A-TO-Z-PLAN.md §H.3, ADR-0005) — real HTTP calls, no SDK dependency
(matches this codebase's httpx-first style elsewhere). Lazily reads the API key so importing this
module never requires one (tests, CI, offline analyzers).

Added while wiring up real credentials: `config/model_registry.yaml` originally pointed every role
at `anthropic`/`openai`, but the free-tier strategy `NEEDED-KEYS.md` itself describes (Gemini +
OpenRouter + Zhipu) had no matching provider adapters at all — the registry couldn't actually run
with the keys that strategy tells you to get first."""

from __future__ import annotations

from typing import Any

import httpx

from common.settings import settings
from llm.provider import LLMResult, Message
from llm.registry import Binding

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Free tier for these models as of the pricing this was written against; refined by a real cost
# meter later if paid-tier usage becomes relevant. 0.0 is accurate for typical free-tier use, not
# a placeholder.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.0, 0.0),
    "gemini-2.5-pro": (0.0, 0.0),
}


class GeminiProvider:
    name = "gemini"

    def complete(
        self, *, binding: Binding, system: str, messages: list[Message],
        max_tokens: int | None = None,
    ) -> LLMResult:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        # Gemini has no "assistant" role — its own history format calls it "model".
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages
        ]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens or binding.max_output_tokens},
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}

        resp = httpx.post(
            f"{_API_BASE}/models/{binding.model}:generateContent",
            params={"key": settings.gemini_api_key}, json=body, timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates: {data}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata", {})
        in_tok = int(usage.get("promptTokenCount", 0))
        out_tok = int(usage.get("candidatesTokenCount", 0))
        pin, pout = _PRICE_PER_MTOK.get(binding.model, (0.0, 0.0))

        return LLMResult(
            text=text, input_tokens=in_tok, output_tokens=out_tok, model=binding.model,
            model_version=binding.model_version, provider=self.name,
            stop_reason=candidates[0].get("finishReason"),
            cost_usd=round(in_tok / 1e6 * pin + out_tok / 1e6 * pout, 6),
        )

    def embed(self, *, binding: Binding, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Gemini embeddings aren't wired up — EMBEDDING role uses a local model"
        )
