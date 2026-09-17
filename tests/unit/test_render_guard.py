"""`seo_core.crawl.render.guarded_route` — the SSRF enforcement point for every request a
rendered page's browser makes (Phase 2/13). No real browser needed: a fake Route/Request double
proves the guard logic itself, which is what actually matters for security."""

from __future__ import annotations

import pytest

from seo_core.crawl.render import guarded_route, render


class _FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = _FakeRequest(url)
        self.aborted = False
        self.continued = False

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


def _resolver(ips: dict[str, list[str]]) -> object:
    return lambda host: ips.get(host, ["93.184.216.34"])  # example.com's real IP as a safe default


@pytest.mark.asyncio
async def test_allowed_host_request_is_continued() -> None:
    route = _FakeRoute("https://example.com/style.css")
    blocked: list[str] = []
    await guarded_route(
        route, allowed_hosts=frozenset({"example.com"}),
        resolver=_resolver({"example.com": ["93.184.216.34"]}), blocked=blocked,
    )
    assert route.continued is True
    assert route.aborted is False
    assert blocked == []


@pytest.mark.asyncio
async def test_disallowed_host_subresource_is_aborted_not_continued() -> None:
    route = _FakeRoute("https://evil-tracker.example/pixel.gif")
    blocked: list[str] = []
    await guarded_route(
        route, allowed_hosts=frozenset({"example.com"}), resolver=_resolver({}), blocked=blocked,
    )
    assert route.aborted is True
    assert route.continued is False
    assert len(blocked) == 1
    assert "evil-tracker.example" in blocked[0]


@pytest.mark.asyncio
async def test_request_resolving_to_a_private_ip_is_aborted() -> None:
    route = _FakeRoute("https://internal.example/data")
    blocked: list[str] = []
    await guarded_route(
        route, allowed_hosts=None, resolver=_resolver({"internal.example": ["10.0.0.5"]}),
        blocked=blocked,
    )
    assert route.aborted is True
    assert "private" in blocked[0]


@pytest.mark.asyncio
async def test_request_to_cloud_metadata_endpoint_is_aborted() -> None:
    route = _FakeRoute("http://169.254.169.254/latest/meta-data/")
    blocked: list[str] = []
    await guarded_route(route, allowed_hosts=None, resolver=None, blocked=blocked)
    assert route.aborted is True
    assert "metadata" in blocked[0]


@pytest.mark.asyncio
async def test_render_short_circuits_on_a_blocked_top_level_url_without_a_browser() -> None:
    """`render()` validates the top-level URL BEFORE ever importing `playwright` — a blocked URL
    must return instantly, never launching a browser at all. Proven by the fact this test needs
    no browser (and no `playwright` import failure) to pass."""
    result = await render("http://169.254.169.254/", allowed_hosts=None)
    assert result.status == 0
    assert result.blocked_reason is not None
    assert "metadata" in result.blocked_reason
