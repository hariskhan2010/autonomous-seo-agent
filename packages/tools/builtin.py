"""Built-in tools registered at import (A-TO-Z-PLAN.md §Phase 2 — first tools).

`fetch_url` is READ_ONLY, project-scoped. It runs the Tier-1 fetcher behind the SSRF guard and
returns a structured result — never raw instructions to the caller (§W)."""

from __future__ import annotations

import asyncio

import httpx
from pydantic import BaseModel, Field

from seo_core.crawl.fetcher import fetch
from tools.registry import Risk, ToolContext, ToolSpec, register


class FetchUrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class FetchUrlOut(BaseModel):
    url: str
    final_url: str
    status: int
    parseable: bool
    truncated: bool
    elapsed_ms: int
    redirect_chain: list[dict[str, str]]
    blocked_reason: str | None = None
    body_sha256: str | None = None
    byte_length: int = 0


def _fetch_url(args: FetchUrlIn, ctx: ToolContext) -> FetchUrlOut:
    from seo_core.crawl.fingerprint import content_hash

    async def _run() -> FetchUrlOut:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await fetch(args.url, client=client, allowed_hosts=ctx.allowed_hosts or None)
        return FetchUrlOut(
            url=r.url, final_url=r.final_url, status=r.status, parseable=r.parseable,
            truncated=r.truncated, elapsed_ms=r.elapsed_ms, redirect_chain=r.redirect_chain,
            blocked_reason=r.blocked_reason,
            body_sha256=content_hash(r.body) if r.body else None,
            byte_length=len(r.body),
        )

    return asyncio.run(_run())


def register_builtins() -> None:
    if "fetch_url" not in {s.name for s in __import__("tools.registry", fromlist=["all_specs"]).all_specs()}:
        register(ToolSpec(
            name="fetch_url",
            version="0.1.0",
            risk=Risk.READ_ONLY,
            input_model=FetchUrlIn,
            output_model=FetchUrlOut,
            handler=_fetch_url,  # type: ignore[arg-type]
            scope="project",
        ))


register_builtins()
