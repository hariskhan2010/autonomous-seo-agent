from __future__ import annotations

from fastapi import APIRouter

from common.settings import settings

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.env, "version": "0.1.0"}
