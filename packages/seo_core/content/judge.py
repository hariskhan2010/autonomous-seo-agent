"""Content judge (A-TO-Z-PLAN.md §Phase 5, §5).

`rule_judge` is the deterministic rubric — always available, and the ground truth the LLM judge
is scored against. `llm_judge` (in the worker) calls the `JUDGE` role, which the registry
guarantees is a different model family than the `WORKER` writer. The judge is never the sole
arbiter of factual correctness."""

from __future__ import annotations

from dataclasses import dataclass, field

from seo_core.content.quality import score_article

RUBRIC_DIMENSIONS = ("coverage", "structure", "keyword_alignment", "linking", "depth")
JUDGE_PROMPT_VERSION = "content-judge/0.1.0"


@dataclass
class RubricScore:
    score: float
    verdict: str  # PASS / REVISE / FAIL
    dimensions: dict[str, float] = field(default_factory=dict)
    scorer: str = "rule"
    notes: str = ""


def rule_judge(
    text: str, *, keyword: str | None = None, target_words: int = 700,
    expected_headings: list[str] | None = None,
) -> RubricScore:
    q = score_article(text, keyword=keyword, target_words=target_words, expected_headings=expected_headings)
    dims = {
        "coverage": q.checks.get("word_count", 0) + sum(v for k, v in q.checks.items() if k.startswith("covers:")),
        "structure": q.checks.get("h2_headings", 0) * 3,
        "keyword_alignment": q.checks.get("kw_in_opening", 0) + q.checks.get("kw_mentions", 0),
        "linking": q.checks.get("internal_links", 0) * 3,
        "depth": min(20, q.score / 5),
    }
    return RubricScore(score=float(q.score), verdict=q.verdict, dimensions=dims, scorer="rule")
