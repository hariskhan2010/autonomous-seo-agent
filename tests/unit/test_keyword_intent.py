"""Intent-classification + clustering golden tests (A-TO-Z-PLAN.md §Phase 4 eval)."""

from __future__ import annotations

import pytest

from seo_core.keywords import classify_intent, cluster_keywords, normalize
from seo_core.keywords.clustering import KeywordInput
from seo_core.keywords.intent import IntentLabel
from tests.eval.runner import prf

# (keyword, expected primary label) — hand-labelled
LEDGER = [
    ("buy gemstone rings online", IntentLabel.TRANSACTIONAL),
    ("gemstone rings price", IntentLabel.TRANSACTIONAL),
    ("best gemstone rings 2026", IntentLabel.COMMERCIAL),
    ("sapphire vs ruby ring", IntentLabel.COMPARISON),
    ("how to clean a gemstone ring", IntentLabel.HOW_TO),
    ("what is a trapiche emerald", IntentLabel.DEFINITIONAL),
    ("gemstone ring repair near me", IntentLabel.LOCAL),
    ("gemstone ring youtube review", IntentLabel.VIDEO),
    ("gemstone meanings", IntentLabel.DEFINITIONAL),
    ("why are emeralds green", IntentLabel.QUESTION),
]


def test_normalize() -> None:
    assert normalize("  Buy  GEMSTONE, Rings!! ") == "buy gemstone rings"


@pytest.mark.parametrize(("kw", "expected"), LEDGER)
def test_primary_intent_matches_ledger(kw: str, expected: IntentLabel) -> None:
    assert classify_intent(kw)[0].label == expected


def test_intent_precision_recall() -> None:
    tp = sum(1 for kw, exp in LEDGER if classify_intent(kw)[0].label == exp)
    scores = prf(tp, len(LEDGER) - tp, len(LEDGER) - tp)
    assert scores["precision"] >= 0.85


def test_mixed_intent_is_multilabel() -> None:
    labels = {s.label for s in classify_intent("best cheap gemstone rings to buy")}
    assert IntentLabel.COMMERCIAL in labels
    assert IntentLabel.TRANSACTIONAL in labels


def test_confidence_is_bounded() -> None:
    for s in classify_intent("how to buy the best gemstone ring near me"):
        assert 0.0 < s.confidence <= 0.99


def test_clustering_is_stable_across_runs() -> None:
    kws = [
        KeywordInput("gemstone rings", 1000), KeywordInput("gemstone ring", 800),
        KeywordInput("buy gemstone rings", 500), KeywordInput("emerald ring", 400),
        KeywordInput("emerald rings for sale", 200), KeywordInput("how to clean gemstone ring", 150),
    ]
    a = [(c.slug, tuple(sorted(c.terms))) for c in cluster_keywords(kws)]
    b = [(c.slug, tuple(sorted(c.terms))) for c in cluster_keywords(kws)]
    assert a == b
    # the two "gemstone ring(s)" terms land together
    joined = next(c for c in cluster_keywords(kws) if "gemstone rings" in c.terms)
    assert "gemstone ring" in joined.terms
