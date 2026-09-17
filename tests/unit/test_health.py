from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_ok() -> None:
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers["x-request-id"]
    assert r.headers["x-correlation-id"]


def test_openapi_served_under_v1() -> None:
    assert client.get("/v1/openapi.json").status_code == 200
