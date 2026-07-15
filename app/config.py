import os
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load environment files
_app_env = os.environ.get("APP_ENV", "development")
APP_ENV = _app_env
load_dotenv(f".env.{_app_env}")

# Server configuration
BASE_URL_ENV = os.environ.get("BASE_URL", "")
if BASE_URL_ENV:
    DOMAIN = os.environ.get("DOMAIN") or urlparse(BASE_URL_ENV).hostname or ""
    SCHEME = os.environ.get("SCHEME") or urlparse(BASE_URL_ENV).scheme or "http"
    BASE_URL = BASE_URL_ENV
else:
    DOMAIN = os.environ.get("DOMAIN", "localhost:3000")
    SCHEME = os.environ.get("SCHEME", "http")
    BASE_URL = f"{SCHEME}://{DOMAIN}"

DATABASE_URL = os.environ.get("DATABASE_URL")

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required")
SESSION_EXPIRE_DAYS = 30

# ActivityPub
ACTIVITYPUB_NS = "https://www.w3.org/ns/activitystreams"
PUBLIC_URI = "https://www.w3.org/ns/activitystreams#Public"

# Pagination
PAGE_SIZE = 20

# SNS
MAX_POST_LENGTH = int(os.environ.get("MAX_POST_LENGTH", "500"))

# SMTP
SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")

# CORS
_cors_raw = os.environ.get("CORS_ORIGINS", "")
if _cors_raw.strip():
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]
elif BASE_URL_ENV:
    CORS_ORIGINS = [BASE_URL]
else:
    CORS_ORIGINS = ["*"]

# File storage
AVATAR_STORAGE_PATH = os.environ.get("AVATAR_STORAGE_PATH", "uploads/avatars")
AVATAR_URL_PREFIX = os.environ.get("AVATAR_URL_PREFIX", "/uploads/avatars")

# Initial owner password (optional - if set, first registration must use this password)
INITIAL_OWNER_PASSWORD = os.environ.get("INITIAL_OWNER_PASSWORD", "")

# S3 / object storage
S3_ENABLED = os.environ.get("S3_ENABLED", "").lower() in ("true", "1", "yes")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")
S3_REGION = os.environ.get("S3_REGION", "auto")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_PUBLIC_URL = os.environ.get("S3_PUBLIC_URL", "")

# Web Push / VAPID
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").replace("\\n", "\n")
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", f"admin@{DOMAIN}")


def get_vapid_keys():
    """VAPID 키를 즉시 조회 (lifespan에서 env 업데이트 후 재조회 가능)."""
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
    pub = os.environ.get("VAPID_PUBLIC_KEY", "").replace("\\n", "\n")
    return priv, pub

# Auto-generate VAPID keys if not configured
if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
    try:
        import base64
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization

        _private_key = ec.generate_private_key(ec.SECP256R1())
        _public_key = _private_key.public_key()

        if not VAPID_PRIVATE_KEY:
            VAPID_PRIVATE_KEY = _private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()

        if not VAPID_PUBLIC_KEY:
            _raw_pub = _public_key.public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
            VAPID_PUBLIC_KEY = base64.urlsafe_b64encode(_raw_pub).rstrip(b"=").decode()
    except Exception:
        pass
