"""Login session management endpoints extracted from _misc.py."""
import re
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, HTTPException

from app.models import LoginSession
from app.config.settings import SESSION_EXPIRE_DAYS
from app.db.database import get_session
from app.core.auth import require_active_auth, get_session_key_from_cookie

logger = logging.getLogger("writ.api.sessions")

sessions_router = APIRouter()

_UA_BROWSER = {
    "chrome": ("Chrome", re.compile(r"Chrome/(\d+)")),
    "edge": ("Edge", re.compile(r"Edg/(\d+)")),
    "firefox": ("Firefox", re.compile(r"Firefox/(\d+)")),
    "safari": ("Safari", re.compile(r"Version/(\d+).*Safari")),
    "opera": ("Opera", re.compile(r"(?:OPR|Opera)/(\d+)")),
}


def _parse_device_name(ua: str) -> str:
    if not ua:
        return "알 수 없는 기기"
    for key, (name, pattern) in _UA_BROWSER.items():
        m = pattern.search(ua)
        if m:
            return f"{name} {m.group(1)}"
    if "Mobile" in ua or "Android" in ua:
        return "모바일 브라우저"
    return "알 수 없는 브라우저"


@sessions_router.get("/sessions")
def list_sessions(request: Request):
    user = require_active_auth(request)
    current_key = get_session_key_from_cookie(request)
    with get_session() as s:
        cutoff = datetime.now(timezone.utc) - timedelta(days=SESSION_EXPIRE_DAYS)
        s.query(LoginSession).filter(LoginSession.user_id == user.id, LoginSession.created_at < cutoff).delete(synchronize_session=False)
        s.commit()
        sessions = s.query(LoginSession).filter_by(user_id=user.id).order_by(LoginSession.last_active.desc()).limit(50).all()
        result = []
        for ls in sessions:
            result.append({
                "id": ls.id,
                "device_name": _parse_device_name(ls.user_agent),
                "ip_address": ls.ip_address,
                "is_current": ls.session_key == current_key,
                "last_active": ls.last_active.isoformat() if ls.last_active else "",
                "created_at": ls.created_at.isoformat() if ls.created_at else "",
            })
    return {"sessions": result}


@sessions_router.post("/sessions/{session_id}/delete")
def delete_session(request: Request, session_id: int):
    user = require_active_auth(request)
    current_key = get_session_key_from_cookie(request)
    with get_session() as s:
        ls = s.query(LoginSession).filter_by(id=session_id, user_id=user.id).first()
        if not ls:
            raise HTTPException(status_code=404, detail="Session not found")
        if ls.session_key == current_key:
            raise HTTPException(status_code=400, detail="현재 사용 중인 기기는 해제할 수 없습니다.")
        s.delete(ls)
        s.commit()
    return {"ok": True}
