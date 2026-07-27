import httpx
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session
from urllib.parse import urlparse

from app.db.database import get_session
from app.core.activitypub import _resolve_actor
from app.models import User, FederationBlock, AllowedServer, ServerSetting

logger = logging.getLogger(__name__)


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


def _resolve_remote_user(handle: str, session: Session | None = None) -> User | None:
    """WebFinger + Actor resolution로 리모트 유저를 DB에 저장하고 반환."""

    clean = handle.lstrip('@')
    if '@' not in clean:
        return None

    local_part, domain = clean.split('@', 1)
    if not _federation_allowed(domain, session):
        return None

    urls = [
        f"https://{domain}/users/{local_part}",
        f"https://{domain}/@{local_part}",
        f"https://{domain}/u/{local_part}",
        f"https://{domain}/profile/{local_part}",
    ]
    try:
        resolved = None
        for url in urls:
            try:
                resolved = _resolve_actor(url)
                if resolved:
                    break
            except Exception:
                continue

        if not resolved:
            wf = httpx.get(
                f"https://{domain}/.well-known/webfinger?resource=acct:{clean}",
                timeout=5,
            )
            if wf.status_code == 200:
                for link in wf.json().get("links", []):
                    if link.get("rel") == "self" and link.get("type", "").endswith("activity+json"):
                        href = link.get("href", "")
                        if href:
                            resolved = _resolve_actor(href)
                            break
        if resolved:
            return resolved
    except Exception as e:
        logger.debug("Failed to resolve remote handle %s: %s", handle, e)
    return None


def resolve_handles_to_ids(handles: list[str]) -> list[int]:
    """핸들 리스트를 받아 DB에서 일치하는 User.id 리스트를 반환합니다."""
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
                    User.username.like(f"{local_part}@%"),
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
        user = _resolve_remote_user(handle)
        if user:
            user_ids.append(user.id)

    return list(set(user_ids))
