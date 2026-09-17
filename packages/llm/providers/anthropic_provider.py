"""Anthropic adapter. The SDK client is created lazily so importing this module never requires
a key (tests, CI, offline analyzers)."""

from __future__ import annotations

from typing import Any

from common.settings import settings
from llm.provider import LLMResult, Message
from llm.registry import Binding

# Published per-MTok pricing; refined by the cost meter later. Keyed by coarse model name.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not settings.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            import anthropic

            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def complete(
        self,
        *,
        binding: Binding,
        system: str,
        messages: list[Message],
        max_tokens: int | None = None,
    ) -> LLMResult:
        client = self._get_client()
        resp = client.messages.create(
            model=binding.model,
            system=system,
            max_tokens=max_tokens or binding.max_output_tokens,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        in_tok, out_tok = resp.usage.input_tokens, resp.usage.output_tokens
        pin, pout = _PRICE_PER_MTOK.get(binding.model, (0.0, 0.0))
        return LLMResult(
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            model=binding.model,
            model_version=getattr(resp, "model", binding.model_version),
            provider=self.name,
            stop_reason=resp.stop_reason,
            cost_usd=round(in_tok / 1e6 * pin + out_tok / 1e6 * pout, 6),
        )

    def embed(self, *, binding: Binding, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Anthropic has no embeddings API; the EMBEDDING role uses another provider"
        )
