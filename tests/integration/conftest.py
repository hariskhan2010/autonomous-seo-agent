from __future__ import annotations

import pytest
from sqlalchemy import text

from db.session import engine


@pytest.fixture(scope="session", autouse=True)
def _require_db() -> None:
    """Skip the whole integration suite if the configured DB isn't reachable + migrated."""
    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1 FROM alembic_version"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"integration DB unavailable / not migrated: {exc}", allow_module_level=True)
