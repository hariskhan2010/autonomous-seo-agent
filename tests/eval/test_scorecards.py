from __future__ import annotations

from tests.eval.scorecards import run_smoke


def test_all_smoke_scorecards_pass_threshold() -> None:
    rows = run_smoke()
    assert rows
    failures = [f"{r.engine}.{r.metric}={r.value} < {r.threshold}" for r in rows if not r.passed]
    assert not failures, failures
