"""Server-info, link-preview, and client-log endpoints extracted from _misc.py."""
import re
import html
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse

from app.models import User, ServerSetting
from app.db.database import get_session
from app.core.auth import require_auth
from app.utils.http import validate_url, validated_get
from app.utils.log import log_admin_action

logger = logging.getLogger("writ.api.meta")

meta_router = APIRouter()


# ── Link Preview ──

@meta_router.post("/link-preview")
def api_link_preview(request: Request, url: str = Form(...)):
    require_auth(request)
    parsed = urlparse(url)
    domain = parsed.netloc
    result = {"url": url, "title": domain, "description": "", "image": ""}
    try:
        if not validate_url(url):
            return result
        resp = validated_get(url, timeout=10, max_size=1024 * 1024)
        if resp and resp.status_code == 200:
            html_text = resp.text
            def _og(n):
                m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', html_text, re.I)
                if not m:
                    m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', html_text, re.I)
                return m.group(1) if m else ""
            og_title = _og("title") or re.search(r'<title>([^<]*)</title>', html_text, re.I)
            result["title"] = html.unescape(_og("title") or (og_title.group(1) if og_title else domain))[:200]
            result["description"] = html.unescape(_og("description") or "")[:400]
            result["image"] = _og("image") or ""
            if result["image"] and result["image"].startswith("/"):
                result["image"] = f"{parsed.scheme}://{parsed.netloc}{result['image']}"
            if result["image"] and not validate_url(result["image"]):
                result["image"] = ""
    except Exception:
        pass
    return result


# ── Server Info ──

def _resolve_admin_users(s, admin_ids_str: str):
    if not admin_ids_str:
        admin_ids_str = "owner"
    handles = [h.strip().lstrip("@") for h in admin_ids_str.split(",") if h.strip()]
    if not handles:
        return []
    return s.query(User).filter(User.username.in_(handles)).all()


@meta_router.get("/server-info")
def api_server_info(request: Request):
    from app.core.auth import get_current_user
    user = get_current_user(request)
    is_admin = bool(user and user.role in ("admin", "moderator", "owner"))
    with get_session() as s:
        settings = ServerSetting.get(s)
        admins = _resolve_admin_users(s, settings.admin_ids or "")
        admin_email = settings.admin_email or (admins[0].email if admins else "")
        return {
            "name": settings.server_name or "WRIT",
            "description": getattr(settings, 'server_description', '') or '',
            "admins": [
                {"username": a.username, "email": (admin_email or a.email) if is_admin else ""}
                for a in admins
            ],
            "logo": settings.logo,
            "favicon": settings.favicon,
            "app_icon": settings.app_icon,
            "enable_reactions": settings.enable_reactions is not False,
        }


# ── Client Log ──

@meta_router.post("/log")
def api_client_log(request: Request):
    try:
        data = request.json()
        action = data.get("action", "client_event")
        details = data.get("details", "")
        ip = request.client.host if request.client else ""
        user = None
        try:
            user = require_auth(request)
        except HTTPException:
            pass
        log_admin_action(
            user_id=user.id if user else None,
            username=user.username if user else "anonymous",
            action=action,
            details=details,
            ip_address=ip,
        )
        return {"ok": True}
    except Exception as e:
        logger.exception("Client log error")
        return JSONResponse({"ok": False, "error": "Failed to save log"}, status_code=400)
