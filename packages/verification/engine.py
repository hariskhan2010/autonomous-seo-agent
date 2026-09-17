"""Verification engine (A-TO-Z-PLAN.md §Phase 8).

After a change: (caller re-fetches the live public URL) → parse → run the named verifier →
before/after diff → passed / failed. Failure is what gates rollback."""

from __future__ import annotations

from dataclasses import dataclass, field

from seo_core.technical.models import PageView
from verification.verifiers import VERIFIERS


@dataclass
class VerificationResult:
    verifier: str
    passed: bool
    detail: dict[str, object] = field(default_factory=dict)
    before_after: dict[str, object] = field(default_factory=dict)


def verify_change(
    verifier: str,
    *,
    live_page: PageView,
    expect: dict[str, object],
    before_page: PageView | None = None,
) -> VerificationResult:
    fn = VERIFIERS.get(verifier)
    if fn is None:
        return VerificationResult(verifier=verifier, passed=False,
                                  detail={"error": f"unknown verifier {verifier!r}"})
    passed, detail = fn(live_page, expect)
    ba: dict[str, object] = {}
    if before_page is not None:
        for f in ("title", "meta_description", "canonical", "h1", "robots_meta"):
            b, a = getattr(before_page, f, None), getattr(live_page, f, None)
            if b != a:
                ba[f] = {"before": b, "after": a}
    return VerificationResult(verifier=verifier, passed=passed, detail=detail, before_after=ba)
