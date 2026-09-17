from __future__ import annotations

from tests.eval.runner import Scorecard, prf


def test_prf_math() -> None:
    assert prf(8, 2, 2) == {"precision": 0.8, "recall": 0.8, "f1": 0.8}


def test_scorecard_threshold_check() -> None:
    sc = Scorecard("trivial", {"precision": 0.95, "recall": 0.9})
    assert sc.check({"precision": 0.9, "recall": 0.85}) == []
    assert sc.check({"precision": 0.99}) == ["precision: 0.95 < 0.99"]
