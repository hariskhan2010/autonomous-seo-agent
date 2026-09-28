"""Phase 13 security-review fixes: fail-closed settings outside dev, stricter bearer-token checks,
and repo-relative-only change paths in the execution adapters."""

from __future__ import annotations

import datetime as dt
import subprocess
import uuid
from pathlib import Path

import jwt
import pytest
from app.auth import principal_from_request
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from common.settings import Settings, settings
from execution.adapters import LocalGitAdapter, UnsafeChangePath, safe_repo_path

UTC = dt.UTC
STRONG = "x" * 40
_SECRETS = ("JWT_SECRET", "APP_SECRET_KEY", "WEBHOOK_SIGNING_SECRET", "ENCRYPTION_KEY")


# ── settings: no public placeholder secrets outside dev/test ─────────────────────────────────


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_placeholder_secrets_refused_outside_dev(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SECRETS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENV", env)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_short_secret_refused_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    for name in _SECRETS:
        monkeypatch.setenv(name, STRONG)
    monkeypatch.setenv("ENCRYPTION_KEY", "too-short")
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_real_secrets_accepted_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    for name in _SECRETS:
        monkeypatch.setenv(name, STRONG)
    assert Settings(_env_file=None).env == "prod"  # type: ignore[call-arg]


@pytest.mark.parametrize("env", ["dev", "test"])
def test_dev_and_test_keep_working_with_defaults(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SECRETS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENV", env)
    assert Settings(_env_file=None).env == env  # type: ignore[call-arg]


# ── bearer tokens ───────────────────────────────────────────────────────────────────────────


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


def _token(**claims: object) -> str:
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def _valid_claims() -> dict[str, object]:
    return {
        "sub": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()), "roles": ["viewer"],
        "exp": dt.datetime.now(UTC) + dt.timedelta(minutes=5),
    }


def test_valid_token_accepted() -> None:
    claims = _valid_claims()
    p = principal_from_request(_request({"Authorization": f"Bearer {_token(**claims)}"}))
    assert str(p.tenant_id) == claims["tenant_id"]


def test_token_without_exp_rejected() -> None:
    claims = _valid_claims()
    del claims["exp"]
    with pytest.raises(HTTPException) as exc:
        principal_from_request(_request({"Authorization": f"Bearer {_token(**claims)}"}))
    assert exc.value.status_code == 401


def test_oauth_state_token_is_not_an_api_credential() -> None:
    # Same signing key as API tokens; must still be refused even if it carried a `sub`.
    claims = {**_valid_claims(), "purpose": "google_oauth"}
    with pytest.raises(HTTPException) as exc:
        principal_from_request(_request({"Authorization": f"Bearer {_token(**claims)}"}))
    assert exc.value.status_code == 401


def test_malformed_dev_headers_are_a_400_not_a_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "env", "dev")
    with pytest.raises(HTTPException) as exc:
        principal_from_request(_request({"X-Dev-User": "nope", "X-Dev-Tenant": "nope"}))
    assert exc.value.status_code == 400


# ── execution adapters: repo-relative paths only ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt", "a/../../outside.txt", "..\\outside.txt", "C:/Windows/x.txt",
        ".git/hooks/post-commit", "sub/.GIT/config", ".github/workflows/ci.yml", "", "/", "a\x00b",
    ],
)
def test_unsafe_paths_rejected(path: str) -> None:
    with pytest.raises(UnsafeChangePath):
        safe_repo_path(path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/index.html", "index.html"), ("./blog//post.md", "blog/post.md"),
     ("docs\\a.md", "docs/a.md"), (".github/CODEOWNERS", ".github/CODEOWNERS")],
)
def test_safe_paths_normalised(path: str, expected: str) -> None:
    assert safe_repo_path(path) == expected


def test_local_git_adapter_refuses_to_write_outside_repo(tmp_path: Path) -> None:
    from execution.adapters import ChangeSpec

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)  # noqa: S603, S607
    adapter = LocalGitAdapter(repo)
    with pytest.raises(UnsafeChangePath):
        adapter.apply(ChangeSpec(op="write_file", path="../escaped.txt", new_content="x"))
    assert not (tmp_path / "escaped.txt").exists()
