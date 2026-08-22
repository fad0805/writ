import base64
import hashlib
import hmac
import time
from functools import lru_cache
from typing import cast

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.config.settings import KEY_ENCRYPTION_SALT, SECRET_KEY

# PBKDF2 반복 횟수. Fernet 암호화는 사용자 AP 개인키처럼 저빈도 경로에서만
# 호출되므로 이 정도 비용은 감수할 만하다(오프라인 무차별 대입 비용 상승).
_PBKDF2_ITERATIONS = 200_000


def generate_keypair():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def _derive_key(secret: str, salt: str) -> bytes:
    if salt:
        digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    else:
        # 레거시 체계: 솔트 없는 sha256 단일 파생 (기존 배포본 호환용)
        digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=8)
def _fernet_for(secret: str, salt: str) -> Fernet:
    # 서명 경로에서 매 요청 복호화가 일어나므로 PBKDF2 반복을 캐시로 절약한다.
    return Fernet(_derive_key(secret, salt))


def _fernet_candidates(secret: str) -> list[Fernet]:
    """복호화 시도 순서: 현재 설정 체계 우선, 레거시 폴백."""
    return [_fernet_for(secret, salt) for salt in dict.fromkeys([KEY_ENCRYPTION_SALT, ""])]


def encrypt_key(plaintext: str, secret: str) -> str:
    return _fernet_for(secret, KEY_ENCRYPTION_SALT).encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str, secret: str) -> str:
    last_exc: Exception | None = None
    for fernet in _fernet_candidates(secret):
        try:
            return fernet.decrypt(ciphertext.encode()).decode()
        except Exception as exc:  # 체계별 시도가 필요한 구조 (현재→레거시 폴백)
            last_exc = exc
    # 레거시 평문 PEM이면 그대로 반환 (역호환)
    if ciphertext.strip().startswith("-----BEGIN"):
        return ciphertext
    raise ValueError("Failed to decrypt private key (SECRET_KEY mismatch or corrupted key)") from last_exc


def reencrypt_private_key(ciphertext: str, *, old_secret: str, old_salt: str, new_secret: str, new_salt: str) -> str:
    """키 순환용: 구 시크릿/솔트 조합으로 복호화해 신 조합으로 다시 암호화한다.

    SECRET_KEY 교체 절차: 1) 구 시크릿으로 이 함수를 통해 모든 사용자 개인키를
    신 시크릿 조합으로 재암호화 2) 환경변수 교체 후 재시작.
    """
    plaintext = Fernet(_derive_key(old_secret, old_salt)).decrypt(ciphertext.encode()).decode()
    return Fernet(_derive_key(new_secret, new_salt)).encrypt(plaintext.encode()).decode()


def get_private_key(user, secret: str) -> str:
    return decrypt_key(user.private_key, secret)


def sign_string(text: str, private_key_pem: str) -> str:
    private_key = cast(
        rsa.RSAPrivateKey,
        serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None,
            backend=default_backend(),
        ),
    )
    signature = private_key.sign(
        text.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def verify_signature(text: str, signature_b64: str, public_key_pem: str) -> bool:
    try:
        public_key = cast(
            rsa.RSAPublicKey,
            serialization.load_pem_public_key(
                public_key_pem.encode("utf-8"),
                backend=default_backend(),
            ),
        )
        signature = base64.b64decode(signature_b64)
        # Try PKCS1v15 first (most common), fall back to PSS
        try:
            public_key.verify(
                signature,
                text.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return True
        except Exception:
            public_key.verify(
                signature,
                text.encode("utf-8"),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
            return True
    except Exception:
        return False


CSRF_EXEMPT_PREFIXES = ("/.well-known/", "/nodeinfo", "/webfinger", "/static/", "/uploads/", "/api/auth/", "/api/push/", "/api/v1/", "/api/v2/", "/api/oauth/", "/oauth/", "/inbox", "/outbox")
CSRF_EXEMPT_EXACT = ("/users/", "/posts/", "/activities/", "/@/")
CSRF_EXEMPT_METHODS = ("GET", "HEAD", "OPTIONS")


def generate_csrf_token(user_id: int) -> str:
    expires = int(time.time()) + 3600
    payload = f"{user_id}:{expires}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def validate_csrf_token(token: str, session_token: str) -> bool:
    if not token or not session_token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        user_id = int(parts[0])
        expires = int(parts[1])
        sig = parts[2]
        expected = hmac.new(SECRET_KEY.encode(), f"{user_id}:{expires}".encode(),
                             hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or expires <= time.time():
            return False
        # Verify session cookie is also valid HMAC-signed (same browser)
        session_decoded = base64.urlsafe_b64decode(session_token.encode()).decode()
        session_parts = session_decoded.split(":")
        session_payload = f"{session_parts[0]}:{session_parts[1]}"
        session_sig = session_parts[2]
        session_expected = hmac.new(SECRET_KEY.encode(), session_payload.encode(),
                                     hashlib.sha256).hexdigest()
        return hmac.compare_digest(session_sig, session_expected)
    except Exception:
        return False


def csrf_token_user_id(token: str) -> int | None:
    """Extract the user_id from a csrf token if its signature is valid.

    Intentionally does not check expiry so an expired token can be used to
    re-issue a fresh one (sliding renewal).
    """
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        user_id = int(parts[0])
        expires = int(parts[1])
        sig = parts[2]
        expected = hmac.new(SECRET_KEY.encode(), f"{user_id}:{expires}".encode(),
                             hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return user_id
    except Exception:
        return None

