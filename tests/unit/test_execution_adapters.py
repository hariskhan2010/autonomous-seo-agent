from __future__ import annotations

import base64

import httpx
import pytest

from execution.adapters import ChangeSpec, GitHubPRAdapter

OWNER, REPO = "acme", "site"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class _FakeGitHub:
    """Minimal in-memory GitHub REST API double, wired via httpx.MockTransport — no network,
    no token, deterministic. Tracks branches/files/PRs well enough to exercise the adapter's
    preview → apply → rollback flow."""

    def __init__(self, base_files: dict[str, str]) -> None:
        self.branches: dict[str, dict[str, str]] = {"main": dict(base_files)}
        self.prs: dict[int, dict[str, object]] = {}
        self._next_pr = 1

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if path.endswith("/git/ref/heads/main") and method == "GET":
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})

        if path.endswith("/git/refs") and method == "POST":
            body = request.content and __import__("json").loads(request.content)
            branch = body["ref"].removeprefix("refs/heads/")
            self.branches[branch] = dict(self.branches["main"])
            return httpx.Response(201, json={"ref": body["ref"]})

        if "/contents/" in path and method == "GET":
            branch = request.url.params.get("ref", "main")
            file_path = path.split("/contents/", 1)[1]
            content = self.branches.get(branch, {}).get(file_path)
            if content is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"content": _b64(content), "sha": f"sha-{file_path}"})

        if "/contents/" in path and method == "PUT":
            body = __import__("json").loads(request.content)
            file_path = path.split("/contents/", 1)[1]
            self.branches[body["branch"]][file_path] = base64.b64decode(body["content"]).decode()
            return httpx.Response(200, json={"content": {"sha": "new-sha"}})

        if "/contents/" in path and method == "DELETE":
            body = __import__("json").loads(request.content)
            file_path = path.split("/contents/", 1)[1]
            self.branches[body["branch"]].pop(file_path, None)
            return httpx.Response(200, json={})

        if path.endswith("/pulls") and method == "POST":
            body = __import__("json").loads(request.content)
            num = self._next_pr
            self._next_pr += 1
            self.prs[num] = {"number": num, "state": "open", "head": body["head"]}
            return httpx.Response(
                201, json={"number": num, "html_url": f"https://github.com/x/pr/{num}"}
            )

        if path.endswith("/pulls") and method == "GET":
            head = request.url.params.get("head", "").split(":", 1)[-1]
            state = request.url.params.get("state")
            matches = [p for p in self.prs.values()
                      if p["head"] == head and (state is None or p["state"] == state)]
            return httpx.Response(200, json=matches)

        if "/pulls/" in path and method == "PATCH":
            num = int(path.rsplit("/", 1)[-1])
            self.prs[num]["state"] = "closed"
            return httpx.Response(200, json=self.prs[num])

        if "/git/refs/heads/" in path and method == "DELETE":
            branch = path.split("/git/refs/heads/", 1)[1]
            self.branches.pop(branch, None)
            return httpx.Response(204)

        raise AssertionError(f"unhandled {method} {path}")


def _adapter(fake: _FakeGitHub) -> GitHubPRAdapter:
    client = httpx.Client(transport=httpx.MockTransport(fake.handler), base_url="https://api.github.com")
    return GitHubPRAdapter(owner=OWNER, repo=REPO, token="test-token", client=client)  # noqa: S106


def test_preview_detects_change() -> None:
    fake = _FakeGitHub({"page.html": "<title>Old</title>"})
    adapter = _adapter(fake)
    spec = ChangeSpec(op="write_file", path="page.html", new_content="<title>New</title>",
                      message="update title")
    preview = adapter.preview(spec)
    assert preview.would_change is True
    assert preview.pre_state_hash is not None


def test_apply_opens_a_pr_on_a_new_branch_not_main() -> None:
    fake = _FakeGitHub({"page.html": "<title>Old</title>"})
    adapter = _adapter(fake)
    spec = ChangeSpec(op="write_file", path="page.html", new_content="<title>New</title>",
                      message="update title")
    outcome = adapter.apply(spec)
    assert outcome.external_ref is not None and "github.com" in outcome.external_ref
    branch = outcome.backup_ref
    assert branch is not None and branch.startswith("seo-agent/")
    assert fake.branches[branch]["page.html"] == "<title>New</title>"
    assert fake.branches["main"]["page.html"] == "<title>Old</title>"  # base untouched


def test_apply_on_delete_removes_file_on_branch_only() -> None:
    fake = _FakeGitHub({"old.html": "stale"})
    adapter = _adapter(fake)
    spec = ChangeSpec(op="delete_file", path="old.html", message="remove stale page")
    outcome = adapter.apply(spec)
    assert "old.html" not in fake.branches[outcome.backup_ref]
    assert fake.branches["main"]["old.html"] == "stale"


def test_rollback_closes_pr_and_deletes_branch() -> None:
    fake = _FakeGitHub({"page.html": "old"})
    adapter = _adapter(fake)
    spec = ChangeSpec(op="write_file", path="page.html", new_content="new", message="m")
    outcome = adapter.apply(spec)
    assert outcome.backup_ref in fake.branches

    ok = adapter.rollback(spec, backup_ref=outcome.backup_ref)
    assert ok is True
    assert outcome.backup_ref not in fake.branches
    pr_number = outcome.detail["pr_number"]
    assert fake.prs[pr_number]["state"] == "closed"


def test_rollback_without_backup_ref_is_a_noop() -> None:
    fake = _FakeGitHub({})
    adapter = _adapter(fake)
    spec = ChangeSpec(op="write_file", path="x.html", new_content="x", message="m")
    assert adapter.rollback(spec, backup_ref=None) is False


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force no fallback token — some dev/CI shells export an ambient GITHUB_TOKEN (e.g. for the
    # `gh` CLI) that `common.settings.settings` would otherwise pick up.
    from common import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "github_token", "")
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        GitHubPRAdapter(owner=OWNER, repo=REPO, token="")
