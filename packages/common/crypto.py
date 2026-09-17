"""Symmetric encryption for secrets at rest (Phase 12/13 — per-project OAuth credential storage,
`packages/db/models/credential.py`). Uses Fernet (AES-128-CBC + HMAC-SHA256) keyed from
`settings.encryption_key` — losing that key makes every encrypted value in the database
permanently unrecoverable, so it belongs in a real secret manager in prod, never committed, and
never rotated without a re-encryption pass over every stored row."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from common.settings import settings


class DecryptionError(ValueError):
    pass


@lru_cache
def _fernet() -> Fernet:
    # settings.encryption_key is an operator-chosen passphrase, not necessarily a valid Fernet key
    # (32 urlsafe-base64-encoded bytes) — derive one deterministically via SHA-256 so any non-empty
    # string works, while the SAME passphrase always derives the SAME key. Cached: re-deriving on
    # every call would be wasted work for a value that never changes within a process lifetime.
    digest = hashlib.sha256(settings.encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "cannot decrypt: wrong ENCRYPTION_KEY or corrupted ciphertext"
        ) from exc
