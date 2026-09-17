"""`llm_judge` / `judge_and_revise` (A-TO-Z-PLAN.md §Phase 5 deferred item), exercised against a
tiny in-test fake `LLMProvider` — no real API key, no network, deterministic."""

from __future__ import annotations

import json

import pytest
import worker.jobs.content as content_module
from worker.jobs.content import judge_and_revise, llm_judge

import llm.router as router_module
from llm.provider import LLMResult
from llm.registry import Binding
from seo_core.content.judge import RubricScore

GOOD_ARTICLE = (
    "# Best Gemstone Rings\n\n" + " ".join(["gemstone ring quality cut clarity"] * 200)
)
WEAK_ARTICLE = "Buy our rings. Free shipping."


class _ScriptedProvider:
    """Returns each entry in `responses` in order, one per `.complete()` call."""

    name = "fake"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    def complete(self, *, binding: Binding, system: str, messages: list[object],
                 max_tokens: int | None = None) -> LLMResult:
        text = self._responses.pop(0)
        return LLMResult(text=text, input_tokens=10, output_tokens=10, model=binding.model,
                         model_version=f"{binding.model}-test", provider="fake")


def _verdict_json(score: float, verdict: str, notes: str = "n") -> str:
    return json.dumps({
        "score": score, "verdict": verdict, "notes": notes,
        "dimensions": {"coverage": 15, "structure": 15, "keyword_alignment": 15,
                       "linking": 15, "depth": score / 5},
    })


@pytest.fixture(autouse=True)
def _clear_provider_cache() -> None:
    router_module._PROVIDERS.clear()
    yield
    router_module._PROVIDERS.clear()


def test_llm_judge_returns_llm_verdict_when_it_agrees_with_the_rule_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        router_module, "_provider",
        lambda name: _ScriptedProvider([_verdict_json(75, "PASS")]),
    )
    result = llm_judge(GOOD_ARTICLE, keyword="gemstone ring")
    assert result.scorer == "llm"
    assert result.verdict == "PASS"


def test_llm_judge_falls_back_to_rule_score_on_wild_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The rule baseline for a thin article is low; a "99, PASS" LLM verdict wildly disagrees.
    monkeypatch.setattr(
        router_module, "_provider", lambda name: _ScriptedProvider([_verdict_json(99, "PASS")]),
    )
    result = llm_judge(WEAK_ARTICLE, keyword="gemstone ring")
    assert result.scorer == "rule"


def test_llm_judge_falls_back_to_rule_score_when_the_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Boom:
        name = "fake"

        def complete(self, **kw: object) -> LLMResult:
            raise RuntimeError("provider down")

    monkeypatch.setattr(router_module, "_provider", lambda name: _Boom())
    result = llm_judge(WEAK_ARTICLE, keyword="gemstone ring")
    assert result.scorer == "rule"


def test_judge_and_revise_short_circuits_on_rule_pass_with_no_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(name: str) -> None:
        raise AssertionError("should not call the LLM when the rule judge already PASSes")

    monkeypatch.setattr(router_module, "_provider", _explode)
    monkeypatch.setattr(content_module, "rule_judge",
                        lambda *a, **kw: RubricScore(score=90, verdict="PASS", scorer="rule"))
    out = judge_and_revise(GOOD_ARTICLE, keyword="gemstone ring")
    assert out["revisions"] == 0
    assert out["judged"].scorer == "rule"
    assert out["judged"].verdict == "PASS"


def test_judge_and_revise_revises_until_pass_or_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fix the rule baseline so the LLM's scripted scores never trip the >30pt disagreement
    # guard — these tests are about the judge->revise->re-judge loop, not the rule/LLM cross-check
    # (that's covered by the `llm_judge` tests above).
    monkeypatch.setattr(content_module, "rule_judge",
                        lambda *a, **kw: RubricScore(score=50, verdict="REVISE", scorer="rule"))
    # judge(REVISE) -> revise -> judge(PASS): one revision, then stop.
    scripted = _ScriptedProvider([
        _verdict_json(50, "REVISE", notes="too thin"),
        "A much longer, revised article body about gemstone rings. " * 30,
        _verdict_json(55, "PASS"),
    ])
    monkeypatch.setattr(router_module, "_provider", lambda name: scripted)
    out = judge_and_revise(WEAK_ARTICLE, keyword="gemstone ring", max_revisions=3)
    assert out["revisions"] == 1
    assert out["judged"].verdict == "PASS"
    assert "revised article" in out["text"]


def test_judge_and_revise_stops_at_max_revisions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content_module, "rule_judge",
                        lambda *a, **kw: RubricScore(score=50, verdict="REVISE", scorer="rule"))
    scripted = _ScriptedProvider([
        _verdict_json(50, "REVISE"), "revision 1 " * 30,
        _verdict_json(50, "REVISE"), "revision 2 " * 30,
        _verdict_json(50, "REVISE"),
    ])
    monkeypatch.setattr(router_module, "_provider", lambda name: scripted)
    out = judge_and_revise(WEAK_ARTICLE, keyword="gemstone ring", max_revisions=2)
    assert out["revisions"] == 2
    assert out["judged"].verdict == "REVISE"
