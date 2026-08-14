import threading
import time
from urllib.parse import urlparse

from app.config.settings import DOMAIN
from app.db.database import get_session
from app.models import AllowedServer, FederationBlock, ServerSetting

# federation_allowed는 인바운드 처리·검색 등에서 도메인마다 DB를 두 번씩
# 조회하는데, 짧은 TTL 캐시로 같은 도메인을 반복 조회할 때의 부하를 줄인다.
# 설정/차단 목록이 바뀌어도 최대 _CACHE_TTL 초 안에는 반영되므로 안전하다.
_CACHE_TTL = 60.0
_allowed_cache: dict[str, tuple[float, bool]] = {}
_allowed_cache_lock = threading.Lock()


def federation_allowed(domain: str) -> bool:
    if not domain:
        return False
    if domain.lower().strip() == DOMAIN.lower().strip():
        return True
    key = domain.lower().strip()
    now = time.monotonic()
    with _allowed_cache_lock:
        cached = _allowed_cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
    with get_session() as s:
        try:
            settings = s.query(ServerSetting).first()
            if not settings:
                result = True
            else:
                mode = settings.federation_mode or "blacklist"
                if mode == "whitelist":
                    allowed = s.query(AllowedServer).filter_by(domain=key).first()
                    result = allowed is not None
                else:
                    blocked = s.query(FederationBlock).filter_by(domain=key).first()
                    result = blocked is None
        except Exception:
            result = False
    with _allowed_cache_lock:
        _allowed_cache[key] = (now, result)
    return result


def _check_fetch_domain_allowed(url: str) -> str | None:
    """Return an error message if the URL's domain is federated-blocked, else None."""
    domain = urlparse(url).hostname or ""
    if domain:
        with get_session() as s:
            mode = ServerSetting.get(s).federation_mode or "blacklist"
            if mode == "whitelist":
                allowed = s.query(AllowedServer).filter_by(domain=domain).first()
                if not allowed:
                    return f"허용되지 않은 서버입니다: {domain}"
            else:
                blocked = s.query(FederationBlock).filter_by(domain=domain).first()
                if blocked:
                    reason = f" ({blocked.reason})" if blocked.reason else ""
                    return f"차단된 서버입니다{reason}: {domain}"
    return None
