import base64
import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime

from fastapi import HTTPException, Request

from app.config.settings import SECRET_KEY, SESSION_EXPIRE_DAYS
from app.db.database import get_session
from app.models import LoginSession, User


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return salt, h.hex()


def verify_password(password: str, salt: str, hashed: str) -> bool:
    _, h = hash_password(password, salt)
    return hmac.compare_digest(h, hashed)


def _sign_session_key(session_key: str, expires: int) -> str:
    payload = f"{session_key}:{expires}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def _decode_session_token(token: str):
    """Decode and verify a session cookie token. Returns (session_key, expires) or None."""
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        session_key = parts[0]
        expires = int(parts[1])
        sig = parts[2]
        expected = hmac.new(SECRET_KEY.encode(), f"{session_key}:{expires}".encode(),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or expires <= time.time():
            return None
        return session_key, expires
    except Exception:
        return None


def create_session(
    user_id: int,
    ip_address: str = "",
    user_agent: str = "",
    linked_user_ids: list[int] | None = None,
) -> str:
    session_key = secrets.token_urlsafe(32)
    expires = int(time.time()) + SESSION_EXPIRE_DAYS * 86400
    with get_session() as s:
        ls = LoginSession(
            user_id=user_id,
            session_key=session_key,
            ip_address=ip_address,
            user_agent=user_agent,
            linked_user_ids=list(linked_user_ids) if linked_user_ids else [],
        )
        s.add(ls)
        s.commit()
    return _sign_session_key(session_key, expires)


def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    decoded = _decode_session_token(token)
    if not decoded:
        return None
    session_key, _ = decoded
    with get_session() as session:
        ls = session.query(LoginSession).filter_by(session_key=session_key).first()
        if ls:
            now = datetime.now(UTC)
            # last_active 갱신은 세션 목록 정렬용이므로 분 단위 해상도면 충분하다.
            # 커밋 빈도를 낮춰(SQLite 단일 writer 락) 읽기 트래픽의 쓰기 경합을 줄인다.
            if not ls.last_active or (now - ls.last_active.replace(tzinfo=UTC)).total_seconds() > 900:
                ls.last_active = now
                session.commit()
            return session.query(User).filter_by(id=ls.user_id, is_remote=False).first()
    return None


def get_session_key_from_cookie(request: Request) -> str | None:
    token = request.cookies.get("session")
    if not token:
        return None
    decoded = _decode_session_token(token)
    return decoded[0] if decoded else None


def session_key_from_token(token: str) -> str | None:
    decoded = _decode_session_token(token)
    return decoded[0] if decoded else None


def delete_session_by_key(session_key: str):
    with get_session() as s:
        s.query(LoginSession).filter_by(session_key=session_key).delete()
        s.commit()


def delete_user_sessions(user_id: int):
    """비밀번호 변경 등으로 해당 사용자의 모든 세션을 무효화한다."""
    with get_session() as s:
        s.query(LoginSession).filter_by(user_id=user_id).delete()
        s.commit()


def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)
    if getattr(user, 'is_frozen', False):
        raise HTTPException(status_code=403, detail="계정이 동결되었습니다.")
    if getattr(user, 'is_suspended', False):
        raise HTTPException(status_code=403, detail="계정이 정지되었습니다.")
    return user


def require_active_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)
    if getattr(user, 'is_frozen', False):
        raise HTTPException(status_code=403, detail="계정이 동결되었습니다.")
    if getattr(user, 'is_suspended', False):
        raise HTTPException(status_code=403, detail="계정이 정지되었습니다.")
    if getattr(user, 'is_deactivated', False):
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다. 설정에서 활성화后可 이용 가능합니다.")
    return user
