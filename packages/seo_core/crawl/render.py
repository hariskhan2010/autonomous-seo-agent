"""Tier 2 — headless-browser fetch via Playwright (A-TO-Z-PLAN.md §Phase 2/13).

For JS-rendered pages Tier 1 (`crawl/fetcher.py`, plain httpx) can't see. Returns the SAME
`FetchResult` shape Tier 1 does, so callers (`worker.jobs.crawl`) dispatch on `CrawlOptions.tier`
without needing two separate code paths downstream of the fetch itself.

The SSRF guard (`crawl/safety.py`) that protects Tier 1 has to be re-applied here at a completely
different layer: a real browser independently resolves DNS and issues its own requests for the
navigation, every redirect, and every subresource (images, scripts, iframes, XHR/fetch calls) —
none of those ever go through Tier 1's httpx client, so validating only the initial URL would
leave the entire rest of the page's network activity unguarded. `page.route("**/*", ...)`
intercepts every one of those requests before Chromium's own network stack sees them, and each one
gets the identical `validate_url` check Tier 1 uses.

Runs inside a container built from `infra/Dockerfile.playwright` (Chromium + its OS-level
dependencies), never inside the api/worker image — nothing else in this codebase needs a browser,
and bundling one into every service's image would be pure bloat."""

from __future__ import annotations

import time
from typing import Any, Protocol

from seo_core.crawl.fetcher import DEFAULT_UA, MAX_BODY_BYTES, FetchResult
from seo_core.crawl.safety import SSRFError, validate_url

DEFAULT_NAV_TIMEOUT_MS = 20_000


class _RequestLike(Protocol):
    url: str


class _RouteLike(Protocol):
    request: _RequestLike

    async def abort(self) -> None: ...
    async def continue_(self) -> None: ...


async def guarded_route(
    route: _RouteLike, *, allowed_hosts: frozenset[str] | None, resolver: object | None,
    blocked: list[str],
) -> None:
    """The actual enforcement point for every request Chromium makes on this page — navigation,
    redirects, and every subresource alike. Pulled out as its own function so it's unit-testable
    against a fake route/request double, with no real browser involved."""
    req_url = route.request.url
    try:
        validate_url(req_url, allowed_hosts=allowed_hosts, resolver=resolver)
    except SSRFError as exc:
        blocked.append(f"{req_url}: {exc}")
        await route.abort()
        return
    await route.continue_()


async def render(
    url: str, *, allowed_hosts: frozenset[str] | None = None, resolver: object | None = None,
    nav_timeout_ms: int = DEFAULT_NAV_TIMEOUT_MS, max_body: int = MAX_BODY_BYTES,
) -> FetchResult:
    started = time.monotonic()
    try:
        validate_url(url, allowed_hosts=allowed_hosts, resolver=resolver)
    except SSRFError as exc:
        return FetchResult(url, url, 0, {}, b"", elapsed_ms=0, parseable=False,
                          blocked_reason=str(exc))

    # Imported lazily: this module is imported by `worker.jobs.crawl` regardless of tier, and the
    # `playwright` package (plus its browser binary) is only ever present in the Tier-2 container.
    from playwright.async_api import async_playwright

    # Subresources the guard blocks (a linked image on a disallowed host, a third-party script,
    # ...) are normal and must NOT fail the whole page — only the main navigation being blocked
    # or erroring does. `blocked` is retained purely as an audit trail, never as a pass/fail signal.
    blocked: list[str] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        try:
            page = await browser.new_page(user_agent=DEFAULT_UA)
            await page.route(
                "**/*",
                lambda route: guarded_route(
                    route, allowed_hosts=allowed_hosts, resolver=resolver, blocked=blocked,
                ),
            )
            try:
                response: Any = await page.goto(
                    url, timeout=nav_timeout_ms, wait_until="networkidle",
                )
            except Exception as exc:  # noqa: BLE001 - a blocked/failed/timed-out navigation is
                # a normal, expected outcome to report, not a crash of the whole crawl job.
                return FetchResult(
                    url=url, final_url=url, status=0, headers={}, body=b"",
                    elapsed_ms=int((time.monotonic() - started) * 1000), parseable=False,
                    blocked_reason=f"navigation failed: {exc}",
                )

            body = (await page.content()).encode("utf-8")
            truncated = len(body) > max_body
            if truncated:
                body = body[:max_body]
            status = response.status if response is not None else 0
            headers = dict(response.headers) if response is not None else {}
            return FetchResult(
                url=url, final_url=page.url, status=status, headers=headers, body=body,
                elapsed_ms=int((time.monotonic() - started) * 1000), truncated=truncated,
                parseable=not truncated and status < 400,
            )
        finally:
            await browser.close()
