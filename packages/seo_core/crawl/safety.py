"""Crawler safety layer (A-TO-Z-PLAN.md §Phase 2, §W, §Q).

Applies to every tier and every fetch. Deterministic — no LLM.

- SSRF / private-network guard: reject requests that resolve to loopback, link-local,
  private (RFC-1918 / ULA), CGNAT, multicast, reserved, or cloud-metadata addresses.
- Re-validate **after every redirect** and pin the connection to the validated IP
  (defeats DNS-rebinding / TOCTOU).
- Scheme allow-list: http / https only.
- Callers pass `allowed_hosts` (verified-ownership list + explicit competitor domains).
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 5

# Link-local metadata endpoints across clouds (AWS/GCP/Azure/OpenStack/Alibaba/DO all use 169.254.169.254).
_METADATA_IPS = frozenset({
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
    ipaddress.ip_address("100.100.100.200"),  # Alibaba
})


class SSRFError(ValueError):
    """A URL failed the safety guard. The message is safe to log."""


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    host: str
    port: int
    ip: str            # the specific IP the connection must be pinned to
    scheme: str


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip in _METADATA_IPS:
        return "cloud metadata endpoint"
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_private:
        return "private address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_reserved or ip.is_unspecified:
        return "reserved address"
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return "CGNAT address"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None and _ip_is_blocked(ip.ipv4_mapped):
            return "ipv4-mapped private address"
        if ip in ipaddress.ip_network("fc00::/7"):
            return "unique-local address"
    return None


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(f"DNS resolution failed for {host!r}: {exc}") from exc
    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        addr = str(info[4][0])
        try:
            out.append(ipaddress.ip_address(addr.split("%")[0]))
        except ValueError:
            continue
    if not out:
        raise SSRFError(f"no usable address for {host!r}")
    return out


def validate_url(
    url: str,
    *,
    allowed_hosts: frozenset[str] | None = None,
    resolver: object | None = None,
) -> ValidatedTarget:
    """Validate a single URL (no redirect following). Returns the pinned target or raises SSRFError.

    `resolver` (test hook) is a callable host -> list[str] of IPs; defaults to system DNS.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFError(f"scheme {scheme!r} not allowed (http/https only)")
    host = (parts.hostname or "").lower()
    if not host:
        raise SSRFError("URL has no host")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise SSRFError(f"host {host!r} is not in the allowed list")
    port = parts.port or (443 if scheme == "https" else 80)

    # A literal IP in the URL is checked directly; otherwise resolve.
    try:
        literal = ipaddress.ip_address(host)
        candidates = [literal]
    except ValueError:
        if resolver is not None:
            candidates = [ipaddress.ip_address(a) for a in resolver(host)]  # type: ignore[operator]
        else:
            candidates = _resolve(host)

    for ip in candidates:
        reason = _ip_is_blocked(ip)
        if reason:
            raise SSRFError(f"{host} resolves to a blocked {reason} ({ip})")

    return ValidatedTarget(url=url, host=host, port=port, ip=str(candidates[0]), scheme=scheme)


def validate_redirect(location: str, *, previous: ValidatedTarget, hop: int, **kw: object) -> ValidatedTarget:
    """Validate a redirect Location. Re-runs the full guard, refuses cross-scheme downgrade
    (https -> http) and enforces the hop cap."""
    if hop >= MAX_REDIRECTS:
        raise SSRFError(f"too many redirects (> {MAX_REDIRECTS})")
    from urllib.parse import urljoin

    target_url = urljoin(previous.url, location)
    target = validate_url(target_url, **kw)  # type: ignore[arg-type]
    if previous.scheme == "https" and target.scheme == "http":
        raise SSRFError("redirect downgrades https -> http")
    return target
