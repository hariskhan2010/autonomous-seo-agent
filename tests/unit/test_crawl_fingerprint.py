from __future__ import annotations

from seo_core.crawl.fingerprint import changed, content_hash, hamming, simhash

BASE = " ".join(f"the quick brown fox number {i} jumps over the lazy dog" for i in range(40))


def test_content_hash_is_stable_and_distinct() -> None:
    assert content_hash("abc") == content_hash(b"abc")
    assert content_hash("abc") != content_hash("abd")


def test_identical_text_zero_distance() -> None:
    assert hamming(simhash(BASE), simhash(BASE)) == 0
    assert changed(simhash(BASE), simhash(BASE)) is False


def test_small_edit_small_distance() -> None:
    tweaked = BASE + " one extra trailing sentence here"
    assert hamming(simhash(BASE), simhash(tweaked)) <= 3
    assert changed(simhash(BASE), simhash(tweaked)) is False


def test_large_rewrite_is_flagged_changed() -> None:
    other = " ".join(f"completely different content block {i} about gemstone certification" for i in range(40))
    assert hamming(simhash(BASE), simhash(other)) > 3
    assert changed(simhash(BASE), simhash(other)) is True


def test_new_page_always_changed() -> None:
    assert changed(None, simhash(BASE)) is True
