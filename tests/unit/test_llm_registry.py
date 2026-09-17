from __future__ import annotations

import pytest

from llm import Message
from llm.registry import Registry, _parse
from llm.roles import Role
from llm.router import complete


def test_default_registry_loads_all_roles() -> None:
    from llm.registry import get_registry

    reg = get_registry()
    for role in Role:
        assert reg.resolve(role).model


def test_judge_family_must_differ_from_worker() -> None:
    bad = {
        "roles": {
            "WORKER": {"provider": "anthropic", "model": "claude-sonnet-5"},
            "JUDGE": {"provider": "anthropic", "model": "claude-opus-5"},
        }
    }
    with pytest.raises(ValueError, match="must differ from WORKER"):
        _parse(bad)


def test_fallback_chain_is_ordered_and_deduped() -> None:
    doc = {
        "roles": {
            "STRATEGY": {"provider": "anthropic", "model": "o", "fallbacks": [{"role": "WORKER"}]},
            "WORKER": {"provider": "anthropic", "model": "s", "fallbacks": [{"role": "FAST"}]},
            "FAST": {"provider": "anthropic", "model": "h", "fallbacks": [{"role": "WORKER"}]},
        }
    }
    reg: Registry = _parse(doc)
    chain = [b.role for b in reg.fallback_chain(Role.STRATEGY)]
    assert chain == [Role.STRATEGY, Role.WORKER, Role.FAST]


def test_router_redaction_gate_blocks_secret_in_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    from common.settings import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-thisisatestsecrettoken123456")
    leak = "here is my key sk-ant-thisisatestsecrettoken123456"
    with pytest.raises(ValueError, match="Secret value detected"):
        complete(Role.FAST, system="You are helpful.", messages=[Message("user", leak)])
