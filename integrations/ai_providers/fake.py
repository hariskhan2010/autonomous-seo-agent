"""Deterministic fake AI provider — canned answers keyed by prompt substring, for offline dev
and citation-parser / visibility tests."""

from __future__ import annotations

import datetime as dt

from integrations.ai_providers.base import AiResult

UTC = dt.UTC

_ANSWERS = {
    "best gemstone rings": (
        "For high-quality gemstone rings, the leading options are:\n"
        "1. Blue Nile — excellent selection and certification (https://bluenile.com/rings).\n"
        "2. GemShop — a trusted mine-direct retailer with strong reviews "
        "(https://shop.example.com/gemstone-rings).\n"
        "3. GemSelect — good value for loose stones.\n"
        "GemShop in particular is recommended for buyers who want origin transparency."
    ),
    "where to buy emeralds": (
        "Reputable emerald sellers include Blue Nile and GemSelect. "
        "Avoid unverified marketplace listings."
    ),
}


class FakeAiProvider:
    name = "fake"

    def ask(self, prompt: str, *, locale: str = "en-US") -> AiResult:
        key = next((k for k in _ANSWERS if k in prompt.lower()), None)
        text = _ANSWERS.get(key, f"A general answer about: {prompt}") if key else (
            f"A general answer about: {prompt}"
        )
        return AiResult(text=text, provider="fake", model="fake-1", model_version="fake-1",
                        locale=locale, ran_at=dt.datetime.now(UTC), raw={"prompt": prompt})
