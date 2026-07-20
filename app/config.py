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
def _sanitize_pem(val: str) -> str:
    if not val:
        return val
    val = val.strip()
    val = val.replace("\\n", "\n").replace("\\r", "")
    return val


def _is_valid_pem_private_key(pem: str) -> bool:
    """Check that a PEM string is a real private key by actually parsing it."""
    if not pem:
        return False
    if not pem.startswith("-----BEGIN ") or not pem.rstrip().endswith("-----"):
        return False
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        load_pem_private_key(pem.encode("utf-8"), password=None)
        return True
    except Exception:
        return False

VAPID_PRIVATE_KEY = _sanitize_pem(os.environ.get("VAPID_PRIVATE_KEY", ""))
VAPID_PUBLIC_KEY = _sanitize_pem(os.environ.get("VAPID_PUBLIC_KEY", ""))
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", f"admin@{DOMAIN}")


def get_vapid_keys():
    """VAPID 키를 즉시 조회 (lifespan에서 env 업데이트 후 재조회 가능)."""
    priv = _sanitize_pem(os.environ.get("VAPID_PRIVATE_KEY", ""))
    pub = _sanitize_pem(os.environ.get("VAPID_PUBLIC_KEY", ""))
    return priv, pub

def init_vapid_keys():
    """Initialize VAPID keys: try DB first, then auto-generate.

    Must be called after models are fully loaded (e.g. from lifespan)
    to avoid circular imports.
    """
    global VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY

    if VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY:
        return

    try:
        from app.models import ServerSetting, get_session
        with get_session() as _s:
            _ss = ServerSetting.get(_s)
            _db_priv = getattr(_ss, 'vapid_private_key', '') or ''
            _db_pub = getattr(_ss, 'vapid_public_key', '') or ''
            _db_priv_san = _sanitize_pem(_db_priv)
            if _db_priv_san and _db_pub and _is_valid_pem_private_key(_db_priv_san):
                VAPID_PRIVATE_KEY = _db_priv_san
                VAPID_PUBLIC_KEY = _sanitize_pem(_db_pub)
                os.environ["VAPID_PRIVATE_KEY"] = VAPID_PRIVATE_KEY
                os.environ["VAPID_PUBLIC_KEY"] = VAPID_PUBLIC_KEY
                if VAPID_PRIVATE_KEY != _db_priv or VAPID_PUBLIC_KEY != _db_pub:
                    try:
                        _ss.vapid_private_key = VAPID_PRIVATE_KEY
                        _ss.vapid_public_key = VAPID_PUBLIC_KEY
                        _s.commit()
                    except Exception:
                        pass
                return
            elif _db_priv_san and _db_pub:
                print(f"[VAPID] DB key invalid (len={len(_db_priv_san)}), regenerating...", flush=True)
                try:
                    _ss.vapid_private_key = ''
                    _ss.vapid_public_key = ''
                    _s.commit()
                    print("[VAPID] Cleared invalid key from DB", flush=True)
                except Exception as _e:
                    print(f"[VAPID] Failed to clear DB key: {_e}", flush=True)
    except Exception as _e:
        print(f"[VAPID] DB read error: {_e}", flush=True)

    if VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY:
        return

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

        os.environ["VAPID_PRIVATE_KEY"] = VAPID_PRIVATE_KEY
        os.environ["VAPID_PUBLIC_KEY"] = VAPID_PUBLIC_KEY

        try:
            from app.models import ServerSetting, get_session
            with get_session() as _s:
                _ss = ServerSetting.get(_s)
                _ss.vapid_private_key = VAPID_PRIVATE_KEY
                _ss.vapid_public_key = VAPID_PUBLIC_KEY
                _s.commit()
                print(f"[VAPID] Auto-generated and saved new key (priv len={len(VAPID_PRIVATE_KEY)})", flush=True)
                try:
                    from app.models import PushSubscription
                    _deleted = _s.query(PushSubscription).delete()
                    _s.commit()
                    if _deleted:
                        print(f"[VAPID] Cleared {_deleted} stale push subscriptions (users must re-subscribe)", flush=True)
                except Exception as _e:
                    print(f"[VAPID] Failed to clear push subscriptions: {_e}", flush=True)
        except Exception as _e:
            print(f"[VAPID] Failed to save auto-generated key to DB: {_e}", flush=True)
    except Exception as _e:
        print(f"[VAPID] Auto-generate error: {_e}", flush=True)
