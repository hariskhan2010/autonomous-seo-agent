from __future__ import annotations

from seo_core.geo import generate_prompt_library


def test_generates_prompts_across_all_kinds_within_range() -> None:
    prompts = generate_prompt_library(
        brand="GemShop", category="gemstone rings",
        seed_keywords=["emerald ring", "sapphire ring", "ruby ring", "opal ring", "topaz ring"],
        competitor_names=["Blue Nile", "GemSelect", "Jewelry.com"],
    )
    kinds = {p.kind for p in prompts}
    assert {"brand", "category", "problem", "product", "comparison", "buying", "industry",
            "competitor"} <= kinds
    assert 30 <= len(prompts) <= 50


def test_deduped_and_stable() -> None:
    prompts = generate_prompt_library(
        brand="GemShop", category="gemstone rings", seed_keywords=["gemstone rings"],
    )
    texts = [p.text for p in prompts]
    assert len(texts) == len(set(t.lower() for t in texts))


def test_no_competitors_or_keywords_still_produces_brand_and_category_prompts() -> None:
    prompts = generate_prompt_library(brand="GemShop", category="gemstone rings")
    kinds = {p.kind for p in prompts}
    assert "brand" in kinds
    assert "category" in kinds
    assert "comparison" not in kinds  # no competitors given
    assert "product" not in kinds  # no seed keywords given


def test_max_prompts_cap_is_respected() -> None:
    prompts = generate_prompt_library(
        brand="GemShop", category="gemstone rings",
        seed_keywords=[f"kw{i}" for i in range(30)],
        competitor_names=[f"comp{i}" for i in range(30)],
        max_prompts=10,
    )
    assert len(prompts) == 10
