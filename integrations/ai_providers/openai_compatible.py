"""One adapter for every OpenAI-compatible endpoint (OpenRouter, Zhipu/GLM, OpenAI, Perplexity)
and a small Gemini shim (A-TO-Z-PLAN.md §Phase 10, §H — provider abstraction).

Lazy: importing never needs a key. Model + endpoint come from a small map, overridable by env."""

from __future__ import annotations

import datetime as dt

import httpx
from integrations.ai_providers.base import AiResult

from common.settings import settings

UTC = dt.UTC

_ENDPOINTS = {
    "openai": ("https://api.openai.com/v1/chat/completions", "gpt-judge-class"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "google/gemini-flash-1.5"),
    "perplexity": ("https://api.perplexity.ai/chat/completions", "sonar"),
    "zhipu": ("https://open.bigmodel.cn/api/paas/v4/chat/completions", "glm-4-flash"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "gemini-2.5-flash"),
}


class OpenAiCompatibleProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self._url, self._model = _ENDPOINTS.get(name, _ENDPOINTS["openrouter"])

    def _key(self) -> str:  # noqa: D401
        return {
            "openai": settings.openai_api_key, "openrouter": settings.openrouter_api_key,
            "perplexity": settings.perplexity_api_key, "zhipu": settings.zhipu_api_key,
            "gemini": settings.gemini_api_key,
        }[self.name] or ""

    def ask(self, prompt: str, *, locale: str = "en-US") -> AiResult:
        if self.name == "gemini":
            url = f"{self._url}/{self._model}:generateContent?key={self._key()}"
            data = httpx.post(url, json={"contents": [{"parts": [{"text": prompt}]}]},
                              timeout=45).json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            data = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key()}"},
                json={"model": self._model, "messages": [{"role": "user", "content": prompt}]},
                timeout=45,
            ).json()
            text = data["choices"][0]["message"]["content"]
        return AiResult(text=text, provider=self.name, model=self._model,
                        model_version=self._model, locale=locale,
                        ran_at=dt.datetime.now(UTC), raw=data)
