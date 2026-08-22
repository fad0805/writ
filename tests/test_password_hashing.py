"""Password hashing: iteration-count self-description + legacy compat."""

import hashlib

from app.core.auth import (
    _LEGACY_PBKDF2_ITERATIONS,
    _PBKDF2_ITERATIONS,
    hash_password,
    needs_password_rehash,
    verify_password,
)


def test_hash_is_self_describing():
    h = hash_password("secret123")
    parts = h.split(":")
    assert len(parts) == 3
    assert int(parts[0]) == _PBKDF2_ITERATIONS
    assert len(parts[1]) == 32  # 16-byte hex salt
    assert len(parts[2]) == hashlib.sha256(b"x").hexdigest().__len__()


def test_verify_roundtrip():
    h = hash_password("mypassword")
    assert verify_password("mypassword", h)
    assert not verify_password("wrong", h)


def test_unique_salts():
    assert hash_password("samepass") != hash_password("samepass")


def test_legacy_salt_digest_compat():
    salt = "aa" * 16
    digest = hashlib.pbkdf2_hmac(
        "sha256", b"pass123", salt.encode(), _LEGACY_PBKDF2_ITERATIONS
    ).hex()
    stored = f"{salt}:{digest}"
    assert verify_password("pass123", stored)
    assert not verify_password("nope", stored)


def test_malformed_stored_rejected():
    assert not verify_password("pass123", "")
    assert not verify_password("pass123", "onlysalt")
    assert not verify_password("pass123", "0:salt:digest")
    assert not verify_password("pass123", "abc:1:2:3")
    assert not verify_password("pass123", "garbage:salt:digest")


def test_needs_rehash_flags_legacy_and_partial():
    salt = "aa" * 16
    digest = "ab" * 32
    legacy = f"{salt}:{digest}"
    assert needs_password_rehash(legacy)
    assert not needs_password_rehash(hash_password("x"))
    assert not needs_password_rehash(f"{_PBKDF2_ITERATIONS}:{salt}:{digest}")
    assert not needs_password_rehash("")
    assert not needs_password_rehash("nonsense")
