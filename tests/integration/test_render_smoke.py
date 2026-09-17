"""Playwright/Chromium actually launches and renders in this environment (Phase 2/13) — a narrow
infra-availability smoke test, separate from the SSRF-guard logic itself
(`tests/unit/test_render_guard.py`, which needs no real browser). Skips cleanly, rather than
failing the suite, when Chromium isn't installed — mirroring how DB-dependent tests skip when
Postgres isn't reachable.

Uses a `data:` URL directly against the Playwright API (not `render()`): `render()`'s own SSRF
guard correctly rejects `data:` URLs (scheme allow-list is http/https only) and blocks loopback
addresses outright, so there's no way to exercise it end-to-end against a real target without
either a live external site (network-flaky, avoided elsewhere in this suite) or a local server on
a permanently-blocked loopback address. This test exists purely to prove the browser mechanics
Tier 2 depends on actually work here; the guard itself is proven in the unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module", autouse=True)
def _require_chromium():
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed", allow_module_level=True)


async def test_chromium_launches_and_renders_a_page() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:  # noqa: BLE001 - no chromium binary in this environment
            pytest.skip(f"chromium binary not available: {exc}")
        try:
            page = await browser.new_page()
            await page.goto("data:text/html,<h1>hello from playwright</h1>")
            content = await page.content()
            assert "hello from playwright" in content
        finally:
            await browser.close()
