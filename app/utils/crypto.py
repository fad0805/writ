import base64
import time
import hmac
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet

from app.config.settings import SECRET_KEY


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


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_key(plaintext: str, secret: str) -> str:
    return _fernet(secret).encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str, secret: str) -> str:
    try:
        return _fernet(secret).decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext


def get_private_key(user, secret: str) -> str:
    return decrypt_key(user.private_key, secret)


def sign_string(text: str, private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
        backend=default_backend(),
    )
    signature = private_key.sign(
        text.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def verify_signature(text: str, signature_b64: str, public_key_pem: str) -> bool:
    try:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("utf-8"),
            backend=default_backend(),
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


CSRF_EXEMPT_PREFIXES = ("/.well-known/", "/nodeinfo", "/webfinger", "/static/", "/uploads/", "/api/auth/", "/api/push/", "/api/v1/", "/api/oauth/", "/oauth/", "/inbox", "/outbox")
CSRF_EXEMPT_EXACT = ("/users/", "/posts/", "/activities/", "/@/")
CSRF_EXEMPT_METHODS = ("GET", "HEAD", "OPTIONS")


def generate_csrf_token(user_id: int) -> str:
    expires = int(time.time()) + 3600
    payload = f"{user_id}:{expires}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
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
                             hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected) or expires <= time.time():
            return False
        # Verify session cookie is also valid HMAC-signed (same browser)
        session_decoded = base64.urlsafe_b64decode(session_token.encode()).decode()
        session_parts = session_decoded.split(":")
        session_payload = f"{session_parts[0]}:{session_parts[1]}"
        session_sig = session_parts[2]
        session_expected = hmac.new(SECRET_KEY.encode(), session_payload.encode(),
                                     hashlib.sha256).hexdigest()[:16]
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
                             hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        return user_id
    except Exception:
        return None

