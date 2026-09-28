"""Tier-1 `fetch()` against an in-memory transport: every request is pinned to the IP the SSRF
guard validated (no second DNS lookup), redirects are re-validated and re-pinned, and the body cap
is enforced while streaming."""

from __future__ import annotations

import ipaddress

import httpx
import pytest

from seo_core.crawl.fetcher import fetch
from seo_core.crawl.safety import _ip_is_blocked

PUBLIC = "93.184.216.34"
PUBLIC_B = "93.184.216.35"


def _resolver(table: dict[str, list[str]]):  # noqa: ANN202 - test double
    return lambda host: table[host]


async def _run(handler, url: str, table: dict[str, list[str]], **kw: object):  # noqa: ANN001, ANN202
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await fetch(url, client=client, resolver=_resolver(table), **kw)  # type: ignore[arg-type]


async def test_https_request_is_pinned_to_the_validated_ip() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>")

    res = await _run(handler, "https://shop.example.com/rings?x=1", {"shop.example.com": [PUBLIC]})
    req = seen[0]
    assert req.url.host == PUBLIC                      # connected to the IP, not re-resolved
    assert req.url.path == "/rings" and req.url.query == b"x=1"
    assert req.headers["host"] == "shop.example.com"   # virtual host preserved
    assert req.extensions["sni_hostname"] == "shop.example.com"  # TLS SNI + cert check by name
    assert req.headers["connection"] == "close"
    assert res.status == 200
    assert res.final_url == "https://shop.example.com/rings?x=1"  # logical URL, not the IP form


async def test_non_default_port_and_ipv6_are_pinned_correctly() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ok")

    await _run(handler, "http://v6.example.com:8080/", {"v6.example.com": ["2606:2800:220:1::1"]})
    req = seen[0]
    assert req.url.host == "2606:2800:220:1::1" and req.url.port == 8080
    assert req.headers["host"] == "v6.example.com:8080"
    assert "sni_hostname" not in req.extensions  # plain http


async def test_redirect_hop_is_revalidated_and_repinned() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers["host"] == "a.example.com":
            return httpx.Response(301, headers={"location": "https://b.example.com/new"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>b</p>")

    res = await _run(
        handler, "https://a.example.com/old",
        {"a.example.com": [PUBLIC], "b.example.com": [PUBLIC_B]},
    )
    assert [r.url.host for r in seen] == [PUBLIC, PUBLIC_B]
    assert res.final_url == "https://b.example.com/new"
    assert len(res.redirect_chain) == 1


async def test_redirect_to_an_internal_address_is_blocked_before_connecting() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://metadata.internal/latest/"})

    res = await _run(
        handler, "http://a.example.com/",
        {"a.example.com": [PUBLIC], "metadata.internal": ["169.254.169.254"]},
    )
    assert len(seen) == 1
    assert res.blocked_reason and "metadata" in res.blocked_reason


async def test_body_cap_is_enforced_while_streaming() -> None:
    produced = 0

    async def endless():  # noqa: ANN202 - async byte stream
        nonlocal produced
        while produced < 50 * 1024:
            produced += 1024
            yield b"x" * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=endless())

    res = await _run(handler, "http://a.example.com/", {"a.example.com": [PUBLIC]}, max_body=4096)
    assert res.truncated and len(res.body) == 4096
    assert not res.parseable
    assert produced < 50 * 1024  # stopped reading early instead of buffering it all


@pytest.mark.parametrize(
    "addr",
    [
        "64:ff9b::7f00:1",        # NAT64 -> 127.0.0.1
        "64:ff9b::a9fe:a9fe",     # NAT64 -> 169.254.169.254
        "2002:0a00:0001::1",      # 6to4 -> 10.0.0.1
        "2001:0:4136:e378:8000:63bf:f5ff:fffe",  # Teredo, client half -> 10.0.0.1
    ],
)
def test_ipv6_forms_embedding_a_private_ipv4_are_blocked(addr: str) -> None:
    # Regression guard: the stdlib already classes 6to4/Teredo as private and all of NAT64
    # as reserved, so these are blocked wholesale by `_ip_is_blocked`.
    assert _ip_is_blocked(ipaddress.ip_address(addr)) is not None

