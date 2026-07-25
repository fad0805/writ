import hashlib
import hmac
import time
import base64
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException

from app.models import User, LoginSession, get_session
from app.config.settings import SECRET_KEY, SESSION_EXPIRE_DAYS

router = APIRouter()


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return salt, h.hex()


def verify_password(password: str, salt: str, hashed: str) -> bool:
    _, h = hash_password(password, salt)
    return hmac.compare_digest(h, hashed)


def _sign_session_key(session_key: str, expires: int) -> str:
    payload = f"{session_key}:{expires}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
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
                            hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected) or expires <= time.time():
            return None
        return session_key, expires
    except Exception:
        return None


def create_session(user_id: int, ip_address: str = "", user_agent: str = "") -> str:
    session_key = secrets.token_urlsafe(32)
    expires = int(time.time()) + SESSION_EXPIRE_DAYS * 86400
    with get_session() as s:
        ls = LoginSession(
            user_id=user_id,
            session_key=session_key,
            ip_address=ip_address,
            user_agent=user_agent,
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
            now = datetime.now(timezone.utc)
            if not ls.last_active or (now - ls.last_active.replace(tzinfo=timezone.utc)).total_seconds() > 300:
                ls.last_active = now
                session.commit()
            return session.query(User).filter_by(id=ls.user_id, is_remote=False).first()
        # Backward compat: old cookies encode user_id as the first field
        try:
            user_id = int(session_key)
            return session.query(User).filter_by(id=user_id, is_remote=False).first()
        except (ValueError, TypeError):
            pass
    return None


def get_session_key_from_cookie(request: Request) -> str | None:
    token = request.cookies.get("session")
    if not token:
        return None
    decoded = _decode_session_token(token)
    return decoded[0] if decoded else None


def delete_session_by_key(session_key: str):
    with get_session() as s:
        s.query(LoginSession).filter_by(session_key=session_key).delete()
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
