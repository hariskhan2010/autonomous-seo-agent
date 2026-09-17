"""SSRF / private-network guard (A-TO-Z-PLAN.md §Phase 2 acceptance).

`resolver` is injected so these run fully offline and deterministically."""

from __future__ import annotations

import pytest

from seo_core.crawl.safety import (
    MAX_REDIRECTS,
    SSRFError,
    validate_redirect,
    validate_url,
)

PUBLIC = ["93.184.216.34"]  # example.com


def r(mapping: dict[str, list[str]]):
    return lambda host: mapping.get(host, PUBLIC)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.100.100.200/",           # Alibaba metadata
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.5.5/",
        "http://100.64.0.1/",                 # CGNAT
        "http://[::1]/",
        "http://[fd00:ec2::254]/",
    ],
)
def test_literal_private_and_metadata_ips_are_blocked(url: str) -> None:
    with pytest.raises(SSRFError):
        validate_url(url)


def test_hostname_resolving_to_private_is_blocked() -> None:
    with pytest.raises(SSRFError, match="private address"):
        validate_url("http://sneaky.example.com/", resolver=r({"sneaky.example.com": ["10.1.2.3"]}))


def test_dns_rebind_public_then_private_is_blocked() -> None:
    # any private address among the resolved set fails the whole request
    with pytest.raises(SSRFError):
        validate_url(
            "http://rebind.example.com/",
            resolver=r({"rebind.example.com": ["93.184.216.34", "127.0.0.1"]}),
        )


def test_non_http_schemes_blocked() -> None:
    for u in ("file:///etc/passwd", "ftp://x/", "gopher://x/", "data:text/plain,hi"):
        with pytest.raises(SSRFError):
            validate_url(u)


def test_public_url_passes_and_pins_ip() -> None:
    t = validate_url("https://example.com/page", resolver=r({}))
    assert t.host == "example.com" and t.ip == "93.184.216.34" and t.port == 443


def test_allowed_hosts_enforced() -> None:
    with pytest.raises(SSRFError, match="not in the allowed list"):
        validate_url("https://evil.com/", allowed_hosts=frozenset({"example.com"}), resolver=r({}))


def test_redirect_to_private_is_blocked() -> None:
    prev = validate_url("https://example.com/", resolver=r({}))
    with pytest.raises(SSRFError):
        validate_redirect("http://169.254.169.254/", previous=prev, hop=1)


def test_redirect_https_to_http_downgrade_blocked() -> None:
    prev = validate_url("https://example.com/", resolver=r({}))
    with pytest.raises(SSRFError, match="downgrades"):
        validate_redirect("http://example.com/x", previous=prev, hop=1, resolver=r({}))


def test_redirect_hop_cap() -> None:
    prev = validate_url("https://example.com/", resolver=r({}))
    with pytest.raises(SSRFError, match="too many redirects"):
        validate_redirect("https://example.com/x", previous=prev, hop=MAX_REDIRECTS, resolver=r({}))
