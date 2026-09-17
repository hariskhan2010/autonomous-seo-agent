"""Change adapters (A-TO-Z-PLAN.md §Phase 8).

An adapter knows how to preview, apply, and roll back one kind of change against one kind of
target. `LocalGitAdapter` works against a real git repo on disk (no external service). `NoOpAdapter`
is for dry runs and tests. `GitHubPRAdapter` takes the same shape against a real hosted repo —
open the change as a PR for human review rather than committing straight to the base branch."""

from __future__ import annotations

import base64
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from common.settings import settings
from seo_core.crawl.fingerprint import content_hash


@dataclass
class ChangeSpec:
    """One concrete edit. `path` + `new_content` for file writes; adapters interpret `op`."""

    op: str                       # "write_file" | "delete_file" | "append"
    path: str
    new_content: str = ""
    message: str = "seo-agent change"


@dataclass
class PreviewResult:
    diff: str
    pre_state_hash: str | None
    would_change: bool


@dataclass
class ApplyResult:
    external_ref: str | None       # commit sha / PR url
    backup_ref: str | None         # revert target
    after_state_hash: str | None
    detail: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class ChangeAdapter(Protocol):
    name: str
    rollback_strategy: str        # native / version_restore / compensating / manual / none

    def read_state(self, spec: ChangeSpec) -> str | None: ...
    def preview(self, spec: ChangeSpec) -> PreviewResult: ...
    def apply(self, spec: ChangeSpec) -> ApplyResult: ...
    def rollback(self, spec: ChangeSpec, *, backup_ref: str | None) -> bool: ...


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


class LocalGitAdapter:
    name = "git_pr"
    rollback_strategy = "native"

    def __init__(self, repo_path: str | Path) -> None:
        self.repo = Path(repo_path)

    def _abs(self, rel: str) -> Path:
        return self.repo / rel.lstrip("/")

    def read_state(self, spec: ChangeSpec) -> str | None:
        p = self._abs(spec.path)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def preview(self, spec: ChangeSpec) -> PreviewResult:
        current = self.read_state(spec) or ""
        target = "" if spec.op == "delete_file" else (
            current + spec.new_content if spec.op == "append" else spec.new_content
        )
        would = current != target
        diff = (
            f"--- {spec.path} (current, {len(current)}b)\n"
            f"+++ {spec.path} (proposed, {len(target)}b)\n"
        )
        return PreviewResult(diff=diff, pre_state_hash=content_hash(current) if current else None,
                             would_change=would)

    def apply(self, spec: ChangeSpec) -> ApplyResult:
        before_sha = _git(self.repo, "rev-parse", "HEAD")
        p = self._abs(spec.path)
        if spec.op == "delete_file":
            if p.exists():
                p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            current = p.read_text(encoding="utf-8") if (spec.op == "append" and p.exists()) else ""
            p.write_text(current + spec.new_content if spec.op == "append" else spec.new_content,
                         encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "-c", "user.email=agent@local", "-c", "user.name=seo-agent",
             "commit", "-m", spec.message, "--no-verify")
        after_sha = _git(self.repo, "rev-parse", "HEAD")
        after_content = self.read_state(spec) or ""
        return ApplyResult(
            external_ref=after_sha, backup_ref=before_sha,
            after_state_hash=content_hash(after_content) if after_content else None,
            detail={"commit": after_sha, "parent": before_sha},
        )

    def rollback(self, spec: ChangeSpec, *, backup_ref: str | None) -> bool:
        if not backup_ref:
            return False
        _git(self.repo, "revert", "--no-edit", "--no-commit", "HEAD")
        _git(self.repo, "-c", "user.email=agent@local", "-c", "user.name=seo-agent",
             "commit", "-m", f"revert: {spec.message}", "--no-verify")
        return True


class GitHubPRAdapter:
    """Real hosted execution: opens every change as a PR against `base_branch` (never commits
    straight to it) — `rollback_strategy = "native"` closes that PR and deletes the branch.
    `backup_ref` carries the working branch name (needed by `rollback`, since a PR isn't found
    by commit sha the way `LocalGitAdapter`'s revert is)."""

    name = "github_pr"
    rollback_strategy = "native"

    def __init__(
        self, *, owner: str, repo: str, base_branch: str = "main", token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.base_branch = base_branch
        self._token = token or settings.github_token
        if not self._token:
            raise RuntimeError("GITHUB_TOKEN (or a GitHub App token) not configured — see NEEDED-KEYS.md")
        self._client = client or httpx.Client(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {self._token}",
                     "Accept": "application/vnd.github+json"},
            timeout=30,
        )

    def _repo_path(self, *parts: str) -> str:
        return "/".join(("/repos", self.owner, self.repo, *parts))

    def _get_file(self, path: str, ref: str) -> tuple[str | None, str | None]:
        """Returns (content, blob_sha), or (None, None) if the file doesn't exist at `ref`."""
        resp = self._client.get(self._repo_path("contents", path), params={"ref": ref})
        if resp.status_code == 404:
            return None, None
        resp.raise_for_status()
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8") if data.get("content") else ""
        return content, str(data["sha"])

    def _target_content(self, spec: ChangeSpec, current: str | None) -> str:
        if spec.op == "delete_file":
            return ""
        if spec.op == "append":
            return (current or "") + spec.new_content
        return spec.new_content

    def read_state(self, spec: ChangeSpec) -> str | None:
        content, _ = self._get_file(spec.path, self.base_branch)
        return content

    def preview(self, spec: ChangeSpec) -> PreviewResult:
        current = self.read_state(spec) or ""
        target = self._target_content(spec, current)
        would = current != target
        diff = (
            f"--- {spec.path} (current, {len(current)}b)\n"
            f"+++ {spec.path} (proposed, {len(target)}b)\n"
        )
        return PreviewResult(diff=diff, pre_state_hash=content_hash(current) if current else None,
                             would_change=would)

    def apply(self, spec: ChangeSpec) -> ApplyResult:
        base_ref = self._client.get(self._repo_path("git", "ref", f"heads/{self.base_branch}"))
        base_ref.raise_for_status()
        base_sha = base_ref.json()["object"]["sha"]

        branch = f"seo-agent/{uuid.uuid4().hex[:12]}"
        self._client.post(
            self._repo_path("git", "refs"),
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        ).raise_for_status()

        current, sha = self._get_file(spec.path, branch)
        target = self._target_content(spec, current)
        if spec.op == "delete_file":
            if sha:
                self._client.request(
                    "DELETE", self._repo_path("contents", spec.path),
                    json={"message": spec.message, "sha": sha, "branch": branch},
                ).raise_for_status()
        else:
            body: dict[str, object] = {
                "message": spec.message,
                "content": base64.b64encode(target.encode("utf-8")).decode("ascii"),
                "branch": branch,
            }
            if sha:
                body["sha"] = sha
            self._client.put(self._repo_path("contents", spec.path), json=body).raise_for_status()

        pr = self._client.post(
            self._repo_path("pulls"),
            json={"title": spec.message, "head": branch, "base": self.base_branch,
                  "body": "Opened by the autonomous SEO agent — review before merging."},
        )
        pr.raise_for_status()
        pr_number = pr.json()["number"]

        return ApplyResult(
            external_ref=pr.json().get("html_url"), backup_ref=branch,
            after_state_hash=content_hash(target) if target else None,
            detail={"branch": branch, "pr_number": pr_number},
        )

    def rollback(self, spec: ChangeSpec, *, backup_ref: str | None) -> bool:
        if not backup_ref:
            return False
        branch = backup_ref
        open_prs = self._client.get(
            self._repo_path("pulls"), params={"head": f"{self.owner}:{branch}", "state": "open"},
        )
        open_prs.raise_for_status()
        for pr in open_prs.json():
            self._client.patch(
                self._repo_path("pulls", str(pr["number"])), json={"state": "closed"},
            ).raise_for_status()
        del_resp = self._client.delete(self._repo_path("git", "refs", f"heads/{branch}"))
        return del_resp.status_code in (204, 404)


class NoOpAdapter:
    name = "noop"
    rollback_strategy = "none"

    def read_state(self, spec: ChangeSpec) -> str | None:
        return None

    def preview(self, spec: ChangeSpec) -> PreviewResult:
        return PreviewResult(diff=f"(noop) {spec.op} {spec.path}", pre_state_hash=None, would_change=True)

    def apply(self, spec: ChangeSpec) -> ApplyResult:
        return ApplyResult(external_ref=None, backup_ref=None, after_state_hash=None)

    def rollback(self, spec: ChangeSpec, *, backup_ref: str | None) -> bool:
        return True


def get_adapter(kind: str, **kw: object) -> ChangeAdapter:
    if kind == "git_pr":
        return LocalGitAdapter(str(kw["repo_path"]))
    if kind == "github_pr":
        return GitHubPRAdapter(
            owner=str(kw["owner"]), repo=str(kw["repo"]),
            base_branch=str(kw.get("base_branch", "main")),
        )
    if kind == "noop":
        return NoOpAdapter()
    raise ValueError(f"no adapter for {kind!r}")
