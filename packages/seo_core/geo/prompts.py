"""GEO prompt-library generator (A-TO-Z-PLAN.md §Phase 10 — deterministic, §V).

Turns a cluster's brand/category/competitor context into a 30-50-prompt battery covering every
`PROMPT_KINDS` bucket (db.models.geo). No LLM, no network — the `FAST`/`STRATEGY` roles can
expand this later; this is the reproducible floor `geo.battery` runs against."""

from __future__ import annotations

from dataclasses import dataclass

MAX_PROMPTS = 50


@dataclass(frozen=True)
class GeneratedPrompt:
    kind: str
    text: str


def _dedupe(prompts: list[GeneratedPrompt]) -> list[GeneratedPrompt]:
    seen: set[str] = set()
    out: list[GeneratedPrompt] = []
    for p in prompts:
        key = p.text.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(GeneratedPrompt(kind=p.kind, text=p.text.strip()))
    return out


def generate_prompt_library(
    *,
    brand: str,
    category: str,
    seed_keywords: list[str] | None = None,
    competitor_names: list[str] | None = None,
    max_prompts: int = MAX_PROMPTS,
) -> list[GeneratedPrompt]:
    """`category` is normally the keyword cluster's label. Returns kind-tagged, deduped prompts,
    capped at `max_prompts` (stable order — brand first, then category/product breadth, then
    competitor breadth last, so truncation drops the least-informative tail first)."""
    keywords = [k.strip() for k in (seed_keywords or []) if k.strip()]
    competitors = [c.strip() for c in (competitor_names or []) if c.strip()]
    prompts: list[GeneratedPrompt] = []

    prompts += [
        GeneratedPrompt("brand", f"What is {brand}?"),
        GeneratedPrompt("brand", f"Is {brand} a good company?"),
        GeneratedPrompt("brand", f"{brand} reviews"),
        GeneratedPrompt("brand", f"What do people say about {brand}?"),
    ]

    if category:
        prompts += [
            GeneratedPrompt("category", f"best {category}"),
            GeneratedPrompt("category", f"top {category} brands"),
            GeneratedPrompt("category", f"leading {category} companies"),
            GeneratedPrompt("problem", f"how to choose {category}"),
            GeneratedPrompt("problem", f"what to look for when buying {category}"),
            GeneratedPrompt("problem", f"common mistakes when buying {category}"),
            GeneratedPrompt("industry", f"top {category} companies"),
            GeneratedPrompt("industry", f"leading brands in {category}"),
            GeneratedPrompt("buying", f"where to buy {category}"),
        ]

    for kw in keywords:
        prompts += [
            GeneratedPrompt("product", f"best {kw}"),
            GeneratedPrompt("product", f"top {kw} recommendations"),
            GeneratedPrompt("product", f"{kw} reviews"),
            GeneratedPrompt("buying", f"best place to buy {kw}"),
        ]

    for comp in competitors:
        prompts += [
            GeneratedPrompt("comparison", f"{brand} vs {comp}"),
            GeneratedPrompt("comparison", f"{comp} vs {brand}"),
            GeneratedPrompt("competitor", f"{comp} reviews"),
            GeneratedPrompt("competitor", f"is {comp} good"),
            GeneratedPrompt("competitor", f"{comp} alternatives"),
        ]

    return _dedupe(prompts)[:max_prompts]
