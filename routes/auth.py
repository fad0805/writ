import hashlib
import hmac
import time
import base64
import secrets
from fastapi import APIRouter, Request, HTTPException

from models import User, get_session
from config import SECRET_KEY, SESSION_EXPIRE_DAYS

router = APIRouter()


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return salt, h.hex()


def verify_password(password: str, salt: str, hashed: str) -> bool:
    _, h = hash_password(password, salt)
    return h == hashed


def create_session(user_id: int) -> str:
    expires = int(time.time()) + SESSION_EXPIRE_DAYS * 86400
    payload = f"{user_id}:{expires}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        user_id = int(parts[0])
        expires = int(parts[1])
        sig = parts[2]
        expected = hmac.new(SECRET_KEY.encode(), f"{user_id}:{expires}".encode(),
                            hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected) or expires <= time.time():
            return None
    except Exception:
        return None
    with get_session() as session:
        return session.query(User).filter_by(id=user_id, is_remote=False).first()


def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)
    return user
