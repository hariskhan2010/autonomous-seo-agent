"""`packages/common/crypto.py` — the encryption layer `OAuthCredential.encrypted_refresh_token`
relies on (Phase 12/13)."""

from __future__ import annotations

import pytest

import common.crypto as crypto_module
from common.crypto import DecryptionError, decrypt_secret, encrypt_secret
from common.settings import settings


@pytest.fixture(autouse=True)
def _reset_fernet_cache():
    crypto_module._fernet.cache_clear()
    yield
    crypto_module._fernet.cache_clear()


def test_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", "a-test-key-thats-not-real-00000")
    ciphertext = encrypt_secret("my-refresh-token")
    assert ciphertext != "my-refresh-token"
    assert decrypt_secret(ciphertext) == "my-refresh-token"


def test_decrypting_with_a_different_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", "key-one-00000000000000000000000")
    crypto_module._fernet.cache_clear()
    ciphertext = encrypt_secret("secret-value")

    monkeypatch.setattr(settings, "encryption_key", "key-two-00000000000000000000000")
    crypto_module._fernet.cache_clear()
    with pytest.raises(DecryptionError):
        decrypt_secret(ciphertext)


def test_decrypting_garbage_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", "a-test-key-thats-not-real-00000")
    with pytest.raises(DecryptionError):
        decrypt_secret("not-valid-ciphertext")
