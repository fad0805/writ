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
