import logging
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

# 설정 모듈은 로깅 설정(app.config.logging)보다 먼저 import된다. handler가 없는
# 시점의 warning은 logging.lastResort가 stderr로 내보내 컨테이너 로그에 남는다.
logger = logging.getLogger("writ.config")

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


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """정수 환경변수를 읽고 [minimum, maximum] 범위를 보장한다.

    값이 잘못되면 조용히 통과해 백그라운드 워커가 죽거나(파싱 실패) 무한 루프에
    들어가므로(주기 0) 기본값/경계값으로 되돌리고 기동 로그에 남긴다.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; falling back to default %d", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s=%d is below minimum %d; clamped to %d", name, value, minimum, minimum)
        return minimum
    if value > maximum:
        logger.warning("%s=%d is above maximum %d; clamped to %d", name, value, maximum, maximum)
        return maximum
    return value


# 사용자 AP 개인키 암호화 전용 솔트. 미설정 시 레거시 체계(솔트 없는
# sha256 단일 파생)로 동작해 기존 배포본과 호환된다. 설정하면 신규
# 암호화는 PBKDF2(솔트+반복) 체계를 쓰고, 복호화는 두 체계를 모두
# 시도한다. 순환 방법은 app/utils/crypto.py의 reencrypt_private_key 참고.
KEY_ENCRYPTION_SALT: str = os.environ.get("KEY_ENCRYPTION_SALT", "")

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
    # 설정이 없으면 와일드카드로 폴백하되, 임의 origin에 쿠키가 실려 보내지는
    # 것을 막기 위해 credentials는 비활성화한다 (main.py에서 사용).
    CORS_ORIGINS = ["*"]

# 명시적으로 origin을 설정한 경우에만 credentialed cross-origin 요청을 허용한다.
# 와일드카드("*")와 allow_credentials=True 조합은 origin을 반영해 되돌려주는
# 미들웨어 특성상 임의 사이트에 인증 정보 접근을 허용하게 된다.
CORS_ALLOW_CREDENTIALS = bool(_cors_raw.strip() or BASE_URL_ENV)

# File storage
AVATAR_STORAGE_PATH = os.environ.get("AVATAR_STORAGE_PATH", "uploads/avatars")
AVATAR_URL_PREFIX = os.environ.get("AVATAR_URL_PREFIX", "/uploads/avatars")

# Orphan media cleanup (days; files older than this with no DB reference get removed by the daily worker)
ORPHAN_MEDIA_MIN_AGE_DAYS = int(os.environ.get("ORPHAN_MEDIA_MIN_AGE_DAYS", "7"))

# Auto-delete worker interval (seconds). 만료된 글 하드 삭제 주기.
# 예전엔 하루 한 번(3시)만 돌았는데, 그때 서버가 바쁘면 남은 글은 다음 날까지
# 갇혔다. 주기를 짧게 두면 부하로 미루더라도 다음 주기에 이어서 처리된다.
_AUTO_DELETE_MIN_SECONDS = 60
_AUTO_DELETE_MAX_SECONDS = 86400
AUTO_DELETE_INTERVAL_SECONDS = _bounded_int_env(
    "AUTO_DELETE_INTERVAL_SECONDS", 3600, _AUTO_DELETE_MIN_SECONDS, _AUTO_DELETE_MAX_SECONDS
)

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
