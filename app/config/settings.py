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
    _scheme = os.environ.get("SCHEME")
    if not _scheme:
        _host = DOMAIN.split(":")[0]
        _scheme = "http" if _host in ("localhost", "127.0.0.1") else "https"
    SCHEME = _scheme
    BASE_URL = f"{SCHEME}://{DOMAIN}"

_database_url = os.environ.get("DATABASE_URL")
if not _database_url:
    raise RuntimeError("DATABASE_URL environment variable is required")
DATABASE_URL: str = _database_url

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    raise RuntimeError("SECRET_KEY environment variable is required")
SECRET_KEY: str = _secret_key
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

# Orphan media cleanup (days; files older than this with no DB reference get removed by the daily worker)
ORPHAN_MEDIA_MIN_AGE_DAYS = int(os.environ.get("ORPHAN_MEDIA_MIN_AGE_DAYS", "7"))

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
