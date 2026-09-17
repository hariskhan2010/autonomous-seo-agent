"""Tool registry contract (A-TO-Z-PLAN.md §I). The DB audit write is stubbed."""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel

import tools.registry as reg
from tools.registry import Risk, ToolContext, ToolError, ToolPermissionError, ToolSpec


class _In(BaseModel):
    n: int


class _Out(BaseModel):
    doubled: int


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(reg, "_persist_call", lambda *a, **k: None)
    reg._REGISTRY.pop("t_double", None)
    reg._REGISTRY.pop("t_secret", None)


def _double(args: _In, ctx: ToolContext) -> _Out:
    return _Out(doubled=args.n * 2)


def _ctx(caller: str = "system") -> ToolContext:
    return ToolContext(tenant_id=uuid.uuid4(), project_id=uuid.uuid4(), caller=caller)


def test_register_and_invoke_roundtrip() -> None:
    reg.register(ToolSpec("t_double", "1.0.0", Risk.READ_ONLY, _In, _Out, _double))
    assert reg.invoke("t_double", {"n": 21}, _ctx()) == {"doubled": 42}


def test_input_validation_rejects_bad_payload() -> None:
    reg.register(ToolSpec("t_double", "1.0.0", Risk.READ_ONLY, _In, _Out, _double))
    with pytest.raises(ToolError, match="invalid input"):
        reg.invoke("t_double", {"n": "not-an-int"}, _ctx())


def test_high_risk_tool_is_forced_to_approval_required() -> None:
    spec = ToolSpec("t_secret", "1.0.0", Risk.HIGH_RISK_WRITE, _In, _Out, _double)
    reg.register(spec)
    assert reg.get("t_secret").permission == "approval_required"


def test_agent_allow_list_enforced() -> None:
    reg.register(ToolSpec(
        "t_double", "1.0.0", Risk.READ_ONLY, _In, _Out, _double,
        allowed_agents=frozenset({"technical"}),
    ))
    with pytest.raises(ToolPermissionError):
        reg.invoke("t_double", {"n": 1}, _ctx(caller="crawler"))
    assert reg.invoke("t_double", {"n": 1}, _ctx(caller="technical")) == {"doubled": 2}


def test_project_scoped_tool_requires_project() -> None:
    reg.register(ToolSpec("t_double", "1.0.0", Risk.READ_ONLY, _In, _Out, _double, scope="project"))
    ctx = ToolContext(tenant_id=uuid.uuid4(), project_id=None, caller="system")
    with pytest.raises(ToolError, match="project-scoped"):
        reg.invoke("t_double", {"n": 1}, ctx)


def test_builtin_fetch_url_is_registered() -> None:
    import tools.builtin  # noqa: F401

    assert "fetch_url" in {s.name for s in reg.all_specs()}
    assert reg.get("fetch_url").risk == Risk.READ_ONLY
