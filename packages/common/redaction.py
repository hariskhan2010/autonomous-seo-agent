"""Secret-redaction layer (A-TO-Z-PLAN.md §52, §N). No secret string may enter an LLM prompt
or a log line. `redact()` is called by the logging processor and by the LLM provider before
every request. A test (tests/unit/test_redaction.py) fails if a known token survives."""

from __future__ import annotations

import re
from collections.abc import Iterable

_PLACEHOLDER = "«REDACTED»"

# Structural patterns for common credential shapes, independent of the known-values list.
_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),          # OpenAI-style
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),      # Anthropic
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),         # Google API key
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),     # GitHub token
    re.compile(r"napi_[a-z0-9]{20,}"),             # Neon API
    re.compile(r"npg_[A-Za-z0-9]{12,}"),           # Neon Postgres password
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),   # Slack
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]


def redact(text: str, known_secrets: Iterable[str] = ()) -> str:
    if not text:
        return text
    for secret in known_secrets:
        if secret and len(secret) >= 8 and secret in text:
            text = text.replace(secret, _PLACEHOLDER)
    for pat in _PATTERNS:
        text = pat.sub(_PLACEHOLDER, text)
    return text


def assert_clean(text: str, known_secrets: Iterable[str]) -> None:
    """Raise if any known secret is still present. Used as a hard gate before LLM calls."""
    for secret in known_secrets:
        if secret and len(secret) >= 8 and secret in text:
            raise ValueError("Secret value detected in outbound text after redaction")
