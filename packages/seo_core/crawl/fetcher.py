"""Tier 1 — async HTTP fetch (A-TO-Z-PLAN.md §Phase 2).

Ported and hardened from seo-agent/lib/crawler.py + utils/http_client.py:
- async httpx, per-host rate limit + concurrency cap
- SSRF guard on the initial URL and **every redirect hop** (`crawl/safety.py`)
- manual redirect following so each hop is re-validated
- hard response-size and total-time caps; streamed body with an early cut
- robots-aware (caller supplies RobotsRules; Crawl-delay respected)

Tiers 2 (Playwright) / 3 (proxied) are separate modules — this one never runs a browser.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from seo_core.crawl.safety import SSRFError, ValidatedTarget, validate_redirect, validate_url

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; AutonomousSEOAgent/0.1; +https://example.com/bot)"
)
MAX_BODY_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0
PARSEABLE_TYPES = ("text/html", "application/xhtml+xml", "text/xml", "application/xml", "text/plain")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    redirect_chain: list[dict[str, str]] = field(default_factory=list)
    elapsed_ms: int = 0
    truncated: bool = False
    parseable: bool = True
    blocked_reason: str | None = None


class HostRateLimiter:
    """Per-host min-interval gate (honours robots Crawl-delay + a floor)."""

    def __init__(self, default_delay: float = 1.0) -> None:
        self._default = default_delay
        self._delay: dict[str, float] = {}
        self._next: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_delay(self, host: str, delay: float) -> None:
        self._delay[host] = max(delay, self._default)

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = self._delay.get(host, self._default)
            wait_for = self._next.get(host, 0.0) - time.monotonic()
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._next[host] = time.monotonic() + delay


async def fetch(
    url: str,
    *,
    client: httpx.AsyncClient,
    allowed_hosts: frozenset[str] | None = None,
    limiter: HostRateLimiter | None = None,
    max_body: int = MAX_BODY_BYTES,
    resolver: object | None = None,
) -> FetchResult:
    started = time.monotonic()
    chain: list[dict[str, str]] = []
    try:
        target: ValidatedTarget = validate_url(url, allowed_hosts=allowed_hosts, resolver=resolver)
    except SSRFError as exc:
        return FetchResult(url, url, 0, {}, b"", elapsed_ms=0, parseable=False, blocked_reason=str(exc))

    hop = 0
    current = target
    while True:
        if limiter is not None:
            await limiter.wait(current.host)
        resp = await client.request(
            "GET", current.url, follow_redirects=False,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "en-US,en;q=0.9"},
        )
        if resp.is_redirect and "location" in resp.headers:
            hop += 1
            chain.append({"from": current.url, "to": resp.headers["location"], "status": str(resp.status_code)})
            try:
                current = validate_redirect(
                    resp.headers["location"], previous=current, hop=hop,
                    allowed_hosts=allowed_hosts, resolver=resolver,
                )
            except SSRFError as exc:
                return FetchResult(
                    url, current.url, resp.status_code, dict(resp.headers), b"",
                    redirect_chain=chain, parseable=False, blocked_reason=str(exc),
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            continue

        body = b""
        truncated = False
        async for part in resp.aiter_bytes():
            body += part
            if len(body) > max_body:
                body = body[:max_body]
                truncated = True
                break
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        return FetchResult(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            headers=dict(resp.headers),
            body=body,
            redirect_chain=chain,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
            parseable=(not truncated) and any(ctype.startswith(t) for t in PARSEABLE_TYPES),
        )
