"""Role -> model binding, loaded from config/model_registry.yaml (ADR-0005).

Guarantees enforced here so the rest of the system can trust them:
- JUDGE provider/model family != WORKER family (bias control, A-TO-Z-PLAN.md §H.1).
- Every binding carries a pinned model + version + ordered fallback chain.
Per-tenant overrides (the `model_registry` table) are layered on top in Phase 12."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from common.settings import settings
from llm.roles import Role


@dataclass(frozen=True)
class Binding:
    role: Role
    provider: str
    model: str
    model_version: str
    fallbacks: tuple[Role, ...] = ()
    max_output_tokens: int = 4096
    dim: int | None = None

    @property
    def family(self) -> str:
        """Coarse model family for the JUDGE != WORKER check."""
        return self.provider


@dataclass(frozen=True)
class Registry:
    bindings: dict[Role, Binding]
    budgets: dict[str, float] = field(default_factory=dict)

    def resolve(self, role: Role) -> Binding:
        if role not in self.bindings:
            raise KeyError(f"No binding for role {role}")
        return self.bindings[role]

    def fallback_chain(self, role: Role) -> list[Binding]:
        seen: set[Role] = set()
        chain: list[Binding] = []
        queue = [role]
        while queue:
            r = queue.pop(0)
            if r in seen:
                continue
            seen.add(r)
            b = self.bindings[r]
            chain.append(b)
            queue.extend(b.fallbacks)
        return chain


def _parse(doc: dict[str, Any]) -> Registry:
    raw_roles = doc.get("roles", {})
    bindings: dict[Role, Binding] = {}
    for name, cfg in raw_roles.items():
        role = Role(name)
        bindings[role] = Binding(
            role=role,
            provider=cfg["provider"],
            model=cfg["model"],
            model_version=cfg.get("model_version", "pinned"),
            fallbacks=tuple(Role(f["role"]) for f in cfg.get("fallbacks", [])),
            max_output_tokens=int(cfg.get("max_output_tokens", 4096)),
            dim=cfg.get("dim"),
        )
    _assert_judge_differs_from_worker(bindings)
    return Registry(bindings=bindings, budgets=dict(doc.get("budgets", {})))


def _assert_judge_differs_from_worker(bindings: dict[Role, Binding]) -> None:
    judge, worker = bindings.get(Role.JUDGE), bindings.get(Role.WORKER)
    if judge and worker and judge.family == worker.family:
        raise ValueError(
            f"JUDGE family ({judge.family}) must differ from WORKER family ({worker.family}) "
            "— bias control, A-TO-Z-PLAN.md §H.1"
        )


@lru_cache
def get_registry() -> Registry:
    path = Path(settings.model_registry_path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _parse(doc)
