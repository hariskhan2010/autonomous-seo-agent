"""Input/output validation (ported from seo-agent/utils/validator.py).

Pure functions, no file IO — the argparse/`save_output` shell from the original is dropped
(A-TO-Z-PLAN.md §D.2). Raises `ValidationError` on bad input."""

from __future__ import annotations

import datetime
import re

_DOMAIN_RE = re.compile(r"^(https?://)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/[^\s]*)?$")


class ValidationError(ValueError):
    pass


def domain(url_or_domain: str) -> str:
    value = str(url_or_domain).strip().strip("/")
    if not _DOMAIN_RE.match(value):
        raise ValidationError(f"Invalid domain: {value!r}")
    return value


def keyword(value: str) -> str:
    v = str(value).strip()
    if not v:
        raise ValidationError("Keyword cannot be empty")
    if len(v) > 200:
        raise ValidationError(f"Keyword too long: {v[:50]}...")
    return v


def date_range(start: str, end: str, max_days: int = 370) -> tuple[str, str]:
    fmt = "%Y-%m-%d"
    try:
        start_d = datetime.datetime.strptime(str(start), fmt).date()
        end_d = datetime.datetime.strptime(str(end), fmt).date()
    except ValueError as exc:
        raise ValidationError(f"Dates must be YYYY-MM-DD. Got {start}/{end}") from exc
    if end_d < start_d:
        raise ValidationError(f"end ({end}) before start ({start})")
    if (end_d - start_d).days > max_days:
        raise ValidationError(f"Date range exceeds {max_days} days")
    return start_d.isoformat(), end_d.isoformat()


def non_empty(data: object, label: str = "output") -> object:
    if data is None:
        raise ValidationError(f"{label} is None")
    if isinstance(data, list | dict | str) and len(data) == 0:
        raise ValidationError(f"{label} is empty")
    return data


def score(value: float, label: str = "score", min_v: float = 0, max_v: float = 100) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be numeric, got {value!r}") from exc
    if not (min_v <= v <= max_v):
        raise ValidationError(f"{label} out of range [{min_v},{max_v}]: {v}")
    return v
