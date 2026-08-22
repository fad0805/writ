"""개인키 암호화 체계 테스트 — 솔트 파생, 레거시 폴백, 순환 경로."""

import pytest

from app.utils import crypto
from app.utils.crypto import decrypt_key, encrypt_key, reencrypt_private_key


def test_roundtrip_legacy_scheme():
    pem, _pub = crypto.generate_keypair()
    token = encrypt_key(pem, "secret-a")
    assert decrypt_key(token, "secret-a") == pem


def test_wrong_secret_still_fails():
    pem, _pub = crypto.generate_keypair()
    token = encrypt_key(pem, "secret-a")
    with pytest.raises(ValueError):
        decrypt_key(token, "other-secret")


def test_salt_set_encrypts_with_pbkdf2(monkeypatch):
    monkeypatch.setattr(crypto, "KEY_ENCRYPTION_SALT", "spicy-salt")
    pem, _pub = crypto.generate_keypair()
    legacy_token = crypto._fernet_for("secret-a", "").encrypt(pem.encode()).decode()
    token = encrypt_key(pem, "secret-a")
    # 새 토큰은 레거시 키와 다른 체계로 만들어진다.
    assert token != legacy_token
    # 그래도 복호화는 된다(현재 체계).
    assert decrypt_key(token, "secret-a") == pem


def test_decrypt_falls_back_to_legacy_ciphertext(monkeypatch):
    """솔트 도입 후에도 기존 배포본의 레거시 암호문을 읽을 수 있어야 한다."""
    monkeypatch.setattr(crypto, "KEY_ENCRYPTION_SALT", "")
    pem, _pub = crypto.generate_keypair()
    legacy_token = encrypt_key(pem, "secret-a")
    monkeypatch.setattr(crypto, "KEY_ENCRYPTION_SALT", "new-salt")
    assert decrypt_key(legacy_token, "secret-a") == pem


def test_reencrypt_private_key_rotation(monkeypatch):
    pem, _pub = crypto.generate_keypair()
    old_token = encrypt_key(pem, "old-secret")
    new_token = reencrypt_private_key(
        old_token,
        old_secret="old-secret",
        old_salt="",
        new_secret="new-secret",
        new_salt="rotated-salt",
    )
    assert new_token != old_token
    # 신 시크릿+솔트로만 복호화된다.
    from cryptography.fernet import Fernet, InvalidToken

    assert Fernet(crypto._derive_key("new-secret", "rotated-salt")).decrypt(new_token.encode()).decode() == pem
    with pytest.raises(InvalidToken):
        Fernet(crypto._derive_key("new-secret", "")).decrypt(new_token.encode())


def test_plaintext_pem_passthrough_unchanged():
    raw = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
    assert decrypt_key(raw, "whatever") == raw
