"""Content fingerprinting (A-TO-Z-PLAN.md §Phase 2 — delta detection).

`content_hash` = exact-match dedupe (sha256 of raw bytes).
`simhash` = near-duplicate detection: two pages with small text edits get a small Hamming
distance, so a re-crawl can tell "meaningfully changed" from "identical / trivial diff"."""

from __future__ import annotations

import hashlib
import re

_TOKEN = re.compile(r"[a-z0-9']+")
_HASH_BITS = 64
_MASK = (1 << _HASH_BITS) - 1


def content_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _shingles(text: str, k: int = 3) -> list[str]:
    tokens = _TOKEN.findall(text.lower())
    if len(tokens) < k:
        return tokens
    return [" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)]


def simhash(text: str) -> str:
    vector = [0] * _HASH_BITS
    for shingle in _shingles(text):
        h = int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(_HASH_BITS):
            vector[bit] += 1 if (h >> bit) & 1 else -1
    fingerprint = 0
    for bit in range(_HASH_BITS):
        if vector[bit] > 0:
            fingerprint |= 1 << bit
    return f"{fingerprint & _MASK:016x}"


def hamming(a: str, b: str) -> int:
    return bin((int(a, 16) ^ int(b, 16)) & _MASK).count("1")


def changed(old_simhash: str | None, new_simhash: str, *, threshold: int = 3) -> bool:
    """True if the page changed meaningfully (Hamming distance > threshold) or is new."""
    if not old_simhash:
        return True
    return hamming(old_simhash, new_simhash) > threshold
