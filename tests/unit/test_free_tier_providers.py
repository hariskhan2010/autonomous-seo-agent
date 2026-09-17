"""Gemini/OpenRouter/Zhipu provider adapters (A-TO-Z-PLAN.md §H.3) — added because
`config/model_registry.yaml` originally pointed every role at anthropic/openai, which don't match
the free-tier keys `NEEDED-KEYS.md` actually recommends getting first. No real network: `httpx.post`
is monkeypatched with a tiny fake response, matching the pattern proven for other httpx-based
adapters in this codebase (e.g. `integrations/analytics/gsc.py`'s tests)."""

from __future__ import annotations

import httpx
import pytest

from common.settings import settings
from llm.provider import Message
from llm.providers.gemini_provider import GeminiProvider
from llm.providers.openrouter_provider import OpenRouterProvider
from llm.providers.zhipu_provider import ZhipuProvider
from llm.registry import Binding
from llm.roles import Role


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("POST", "https://x"),
                response=httpx.Response(self.status_code),
            )


_BINDING = Binding(role=Role.WORKER, provider="gemini", model="gemini-2.5-flash",
                  model_version="pinned", max_output_tokens=100)


def test_gemini_complete_parses_a_real_shaped_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    captured: dict[str, object] = {}

    def fake_post(url: str, *, params: dict[str, object], json: dict[str, object],
                  timeout: float) -> _FakeResponse:
        captured["url"], captured["json"] = url, json
        return _FakeResponse(200, {
            "candidates": [{"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1},
        })

    monkeypatch.setattr(httpx, "post", fake_post)
    result = GeminiProvider().complete(
        binding=_BINDING, system="be terse", messages=[Message("user", "say ok")],
    )
    assert result.text == "OK"
    assert result.input_tokens == 5
    assert result.output_tokens == 1
    assert result.provider == "gemini"
    assert "gemini-2.5-flash" in str(captured["url"])
    assert captured["json"]["system_instruction"]["parts"][0]["text"] == "be terse"  # type: ignore[index]


def test_gemini_maps_assistant_role_to_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    captured: dict[str, object] = {}

    def fake_post(url: str, *, params: object, json: dict[str, object],
                  timeout: float) -> _FakeResponse:
        captured["json"] = json
        return _FakeResponse(200, {
            "candidates": [{"content": {"parts": [{"text": "hi"}]}, "finishReason": "STOP"}],
            "usageMetadata": {},
        })

    monkeypatch.setattr(httpx, "post", fake_post)
    GeminiProvider().complete(
        binding=_BINDING, system="",
        messages=[Message("user", "hi"), Message("assistant", "hello")],
    )
    roles = [c["role"] for c in captured["json"]["contents"]]  # type: ignore[index]
    assert roles == ["user", "model"]


def test_gemini_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # explicit empty, not relying on a default — a real key may already be configured for this env
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiProvider().complete(binding=_BINDING, system="", messages=[Message("user", "hi")])


def test_openrouter_complete_parses_a_real_shaped_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    captured: dict[str, object] = {}

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, object],
                  timeout: float) -> _FakeResponse:
        captured["headers"], captured["json"] = headers, json
        return _FakeResponse(200, {
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0},
        })

    monkeypatch.setattr(httpx, "post", fake_post)
    binding = Binding(role=Role.JUDGE, provider="openrouter",
                      model="nvidia/nemotron-3-super-120b-a12b:free", model_version="pinned")
    result = OpenRouterProvider().complete(
        binding=binding, system="judge this", messages=[Message("user", "score it")],
    )
    assert result.text == "OK"
    assert result.cost_usd == 0.0
    assert captured["headers"]["Authorization"] == "Bearer sk-or-test"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "judge this"}  # type: ignore[index]


def test_openrouter_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    binding = Binding(role=Role.JUDGE, provider="openrouter", model="x", model_version="pinned")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterProvider().complete(binding=binding, system="", messages=[Message("user", "hi")])


def test_zhipu_complete_parses_a_real_shaped_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "zhipu_api_key", "test-key")

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, object],
                  timeout: float) -> _FakeResponse:
        return _FakeResponse(200, {
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        })

    monkeypatch.setattr(httpx, "post", fake_post)
    binding = Binding(role=Role.FAST, provider="zhipu", model="glm-4.5-flash",
                      model_version="glm-4.5-flash")
    result = ZhipuProvider().complete(binding=binding, system="", messages=[Message("user", "hi")])
    assert result.text == "OK"
    assert result.provider == "zhipu"


def test_zhipu_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "zhipu_api_key", "")
    binding = Binding(role=Role.FAST, provider="zhipu", model="glm-4.5-flash",
                      model_version="glm-4.5-flash")
    with pytest.raises(RuntimeError, match="ZHIPU_API_KEY"):
        ZhipuProvider().complete(binding=binding, system="", messages=[Message("user", "hi")])
