"""Keyword normalisation (A-TO-Z-PLAN.md §Phase 4, §V — deterministic)."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s\-']", re.UNICODE)
_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or"}


def normalize(term: str) -> str:
    t = unicodedata.normalize("NFKC", term).casefold().strip()
    t = _PUNCT.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t


def _singular(w: str) -> str:
    if len(w) > 4 and w.endswith(("ies",)):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def tokens(term: str, *, drop_stopwords: bool = True, min_len: int = 2, stem: bool = True) -> set[str]:
    words = normalize(term).split()
    out = {(_singular(w) if stem else w) for w in words if len(w) >= min_len}
    return out - _STOP if drop_stopwords else out
