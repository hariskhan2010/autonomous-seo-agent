"""Progressive evaluation harness (A-TO-Z-PLAN.md §P). Phase 0: loader + scorecard shell +
one trivial case so later phases add datasets, not infrastructure."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"


@dataclass
class Scorecard:
    name: str
    metrics: dict[str, float] = field(default_factory=dict)

    def check(self, thresholds: dict[str, float]) -> list[str]:
        return [
            f"{k}: {self.metrics.get(k)!r} < {v}"
            for k, v in thresholds.items()
            if self.metrics.get(k, 0.0) < v
        ]


def load_golden(dataset: str) -> list[dict]:
    path = GOLDEN / dataset / "cases.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}
