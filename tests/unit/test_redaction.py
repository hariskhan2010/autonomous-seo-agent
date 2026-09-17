"""A-TO-Z-PLAN.md §N — a test that fails if a known secret token can survive redaction."""

from __future__ import annotations

import pytest

from common.redaction import assert_clean, redact

KNOWN = ["sk-ant-abcdef0123456789ABCDEF", "napi_supersecretvalue123456789"]


@pytest.mark.parametrize("secret", KNOWN)
def test_known_secret_is_removed(secret: str) -> None:
    text = f"call failed with Authorization: Bearer {secret} on retry"
    assert secret not in redact(text, KNOWN)


def test_structural_patterns_catch_unlisted_keys() -> None:
    text = "leaked ghp_0123456789abcdefghijABCD and AIzaSyA1234567890abcdefghijklmnop"
    out = redact(text, [])
    assert "ghp_" not in out
    assert "AIzaSy" not in out


def test_assert_clean_raises_on_leak() -> None:
    with pytest.raises(ValueError):
        assert_clean(f"prompt containing {KNOWN[0]}", KNOWN)


def test_assert_clean_passes_when_clean() -> None:
    assert_clean("a perfectly ordinary prompt", KNOWN)
