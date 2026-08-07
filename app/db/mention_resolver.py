import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import or_
from sqlalchemy.orm import Session
from urllib.parse import urlparse

from app.db.database import get_session, username_prefix_like
from app.core.activitypub import _resolve_actor
from app.models import User, FederationBlock, AllowedServer, ServerSetting
from app.utils.http import safe_fetch

logger = logging.getLogger(__name__)

_RESOLUTION_CACHE: dict[str, tuple[float, int | None]] = {}
_CACHE_LOCK = threading.Lock()
_SUCCESS_TTL = 30 * 60
_FAILURE_TTL = 15 * 60
_RESOLVE_TIMEOUT = 6

_MISS = object()


def _cache_get(handle: str):
    with _CACHE_LOCK:
        entry = _RESOLUTION_CACHE.get(handle)
        if not entry:
            return _MISS
        ts, user_id = entry
        ttl = _SUCCESS_TTL if user_id is not None else _FAILURE_TTL
        if time.monotonic() - ts > ttl:
            _RESOLUTION_CACHE.pop(handle, None)
            return _MISS
        return user_id


def _cache_set(handle: str, user_id: int | None) -> None:
    with _CACHE_LOCK:
        _RESOLUTION_CACHE[handle] = (time.monotonic(), user_id)


def _federation_allowed(domain: str, session: Session | None = None) -> bool:
    domain = domain.lower().strip()
    if session is None:
        with get_session() as s:
            return _federation_allowed(domain, s)

    try:
        settings = ServerSetting.get(session)
        if not settings:
            return True

        mode = settings.federation_mode or "blacklist"
        if mode == "whitelist":
            return session.query(AllowedServer).filter_by(domain=domain).first() is not None
        else:
            return session.query(FederationBlock).filter_by(domain=domain).first() is None
    except Exception:
        return False


def _webfinger_actor_url(clean: str, domain: str) -> str | None:
    """WebFinger lookup → canonical actor URL (single round trip)."""
    try:
        resp = safe_fetch(
            f"https://{domain}/.well-known/webfinger?resource=acct:{clean}",
            timeout=_RESOLVE_TIMEOUT,
            headers={"Accept": "application/jrd+json, application/json"},
        )
        if resp and resp.status_code == 200:
            for link in resp.json().get("links", []):
                if link.get("rel") == "self" and link.get("type", "").endswith("activity+json"):
                    href = link.get("href", "")
                    if href:
                        return href
    except Exception as e:
        logger.debug("WebFinger failed for %s: %s", clean, e)
    return None


def _resolve_remote_user(handle: str, session: Session | None = None) -> User | None:
    """WebFinger + Actor resolution로 리모트 유저를 DB에 저장하고 반환.

    결과(성공/실패)를 메모리에 캐시해 반복 멘션 시 네트워크 호출을 생략한다.
    """

    clean = handle.lstrip('@')
    if '@' not in clean:
        return None

    cached = _cache_get(clean)
    if cached is not _MISS:
        if cached is None:
            return None
        with get_session() as s:
            user = s.query(User).get(cached)
            if user:
                return user

    local_part, domain = clean.split('@', 1)
    if not _federation_allowed(domain, session):
        _cache_set(clean, None)
        return None

    resolved = None
    try:
        actor_url = _webfinger_actor_url(clean, domain)
        if actor_url:
            resolved = _resolve_actor(actor_url, lightweight=True, timeout=_RESOLVE_TIMEOUT)
            if resolved:
                _cache_set(clean, resolved.id)
                return resolved

        if not resolved:
            candidates = [
                f"https://{domain}/users/{local_part}",
                f"https://{domain}/u/{local_part}",
                f"https://{domain}/profile/{local_part}",
            ]
            with ThreadPoolExecutor(max_workers=len(candidates)) as ex:
                futures = [ex.submit(_resolve_actor, url, lightweight=True, timeout=_RESOLVE_TIMEOUT) for url in candidates]
                for fut in futures:
                    try:
                        resolved = fut.result()
                        if resolved:
                            break
                    except Exception:
                        continue
            if resolved:
                _cache_set(clean, resolved.id)
                return resolved
    except Exception as e:
        logger.debug("Failed to resolve remote handle %s: %s", handle, e)

    _cache_set(clean, None)
    return None


def resolve_handles_to_ids(handles: list[str], resolve_remote: bool = True) -> list[int]:
    """핸들 리스트를 받아 DB에서 일치하는 User.id 리스트를 반환합니다.

    resolve_remote=False면 DB/캐시 기반 조회만 하고 네트워크(WebFinger/actor) 해석을
    하지 않는다. 포스트 생성 응답을 막지 않도록 요청 경로에서는 False를 쓰고,
    리모트 멘션 해석은 백그라운드에서 이뤄진다.
    """
    if not handles:
        return []

    user_ids = []
    unresolved = []
    with get_session() as s:
        for handle in handles:
            clean_handle = handle.lstrip('@')
            if '@' in clean_handle:
                local_part, domain = clean_handle.split('@', 1)
                u = s.query(User).filter(
                    or_(User.username == local_part, User.username == clean_handle),
                    User.is_remote == True
                ).first()
                if u and u.remote_url:
                    parsed = urlparse(u.remote_url)
                    if parsed.hostname and parsed.hostname.lower() == domain.lower():
                        user_ids.append(u.id)
                        continue
                candidates = s.query(User).filter(
                    username_prefix_like(User.username, f"{local_part}@"),
                    User.is_remote == True
                ).all()
                found = False
                for _c in candidates:
                    if _c.remote_url:
                        _p = urlparse(_c.remote_url)
                        if _p.hostname and _p.hostname.lower() == domain.lower():
                            user_ids.append(_c.id)
                            found = True
                            break
                if not found:
                    unresolved.append(handle)
            else:
                u = s.query(User).filter(
                    User.username == clean_handle,
                    User.is_remote == False
                ).first()
                if u:
                    user_ids.append(u.id)

    for handle in unresolved:
        if not resolve_remote:
            continue
        user = _resolve_remote_user(handle)
        if user:
            user_ids.append(user.id)

    return list(set(user_ids))
