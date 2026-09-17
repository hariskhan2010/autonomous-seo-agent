"""Guards against the `secret_field_names` bug: a name listed there with no matching Settings
field silently never gets redacted, because `getattr(self, name, "")` falls through to "" and
`secret_values()` drops empty values. See `packages/common/settings.py`."""

from __future__ import annotations

from common.settings import Settings


def test_every_declared_secret_field_name_exists_on_settings() -> None:
    s = Settings()
    missing = [name for name in s.secret_field_names if name not in type(s).model_fields]
    assert missing == []


def test_secret_values_picks_up_a_configured_github_token() -> None:
    s = Settings(github_token="ghp_" + "x" * 30)  # noqa: S106
    assert s.github_token in s.secret_values()
