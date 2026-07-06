import os
from dotenv import load_dotenv

# Load environment files
_app_env = os.environ.get("APP_ENV", "development")
load_dotenv(".env")
load_dotenv(f".env.{_app_env}")

# Server configuration
DOMAIN = os.environ.get("DOMAIN", "localhost:8000")
SCHEME = os.environ.get("SCHEME", "http")
BASE_URL = f"{SCHEME}://{DOMAIN}"

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./sns_blog.db")

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-to-a-random-secret-key")
SESSION_EXPIRE_DAYS = 30

# ActivityPub
ACTIVITYPUB_NS = "https://www.w3.org/ns/activitystreams"
PUBLIC_URI = "https://www.w3.org/ns/activitystreams#Public"

# Pagination
PAGE_SIZE = 20

# SNS
MAX_POST_LENGTH = int(os.environ.get("MAX_POST_LENGTH", "500"))

# CORS
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

# File storage
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
AVATAR_STORAGE_PATH = os.environ.get("AVATAR_STORAGE_PATH", "uploads/avatars")
AVATAR_URL_PREFIX = os.environ.get("AVATAR_URL_PREFIX", "/uploads/avatars")

# S3 / object storage
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")
S3_REGION = os.environ.get("S3_REGION", "auto")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_PUBLIC_URL = os.environ.get("S3_PUBLIC_URL", "")
