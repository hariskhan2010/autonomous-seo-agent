"""Concrete verifiers (A-TO-Z-PLAN.md §Phase 8 — immediate technical only, §K.5).

Each takes the parsed live page + the expected assertion and returns (passed, detail).
Never trusts a 200 from the write API — the caller re-fetches the public URL first."""

from __future__ import annotations

from collections.abc import Callable

from seo_core.technical.models import PageView

Verifier = Callable[[PageView, dict[str, object]], tuple[bool, dict[str, object]]]


def _canonical(page: PageView, expect: dict[str, object]) -> tuple[bool, dict[str, object]]:
    want = str(expect.get("canonical") or page.final_url).rstrip("/")
    got = (page.canonical or "").rstrip("/")
    return got == want, {"expected": want, "got": got}


def _metadata(page: PageView, expect: dict[str, object]) -> tuple[bool, dict[str, object]]:
    ok = True
    detail: dict[str, object] = {}
    for field in ("title", "meta_description", "h1"):
        if field in expect:
            got = getattr(page, field, None)
            detail[field] = {"expected": expect[field], "got": got}
            if (got or "").strip() != str(expect[field]).strip():
                ok = False
    return ok, detail


def _internal_link_added(page: PageView, expect: dict[str, object]) -> tuple[bool, dict[str, object]]:
    target = str(expect["target"]).rstrip("/")
    present = any(link.rstrip("/") == target for link in page.internal_links)
    return present, {"target": target, "present": present}


def _schema(page: PageView, expect: dict[str, object]) -> tuple[bool, dict[str, object]]:
    want_type = str(expect.get("type", "")).lower()
    types = {str(b.get("@type", "")).lower() for b in page.schema_blocks}
    ok = bool(page.schema_blocks) and (not want_type or want_type in types)
    return ok, {"expected_type": want_type or "any", "found_types": sorted(types)}


def _redirect_added(page: PageView, expect: dict[str, object]) -> tuple[bool, dict[str, object]]:
    final = str(expect["to"]).rstrip("/")
    ok = page.final_url.rstrip("/") == final and len(page.redirect_chain) >= 1
    return ok, {"final_url": page.final_url, "expected_final": final, "hops": len(page.redirect_chain)}


def _noindex_removed(page: PageView, _expect: dict[str, object]) -> tuple[bool, dict[str, object]]:
    return not page.is_noindex, {"robots_meta": page.robots_meta}


VERIFIERS: dict[str, Verifier] = {
    "canonical_change": _canonical,
    "metadata_change": _metadata,
    "internal_link_added": _internal_link_added,
    "schema_change": _schema,
    "redirect_added": _redirect_added,
    "content_change": _metadata,
    "noindex_removed": _noindex_removed,
}
