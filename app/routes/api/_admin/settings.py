"Server settings and admin log endpoints."

from fastapi import APIRouter, Form, HTTPException, Request

from app.core.auth import require_auth
from app.db.database import get_session
from app.models import AdminLog, ServerSetting
from app.routes.api._pwa import _delete_favicon, _delete_pwa_icons, _save_favicon, _save_pwa_icons
from app.utils.datetime import _fmt_dt
from app.utils.log import log_admin_action
from app.utils.storage import get_storage

router = APIRouter()


@router.get("/admin/settings")
def api_admin_get_settings(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        settings = ServerSetting.get(s)
        return {
            "server_name": settings.server_name,
            "server_description": getattr(settings, 'server_description', '') or '',
            "logo": settings.logo,
            "favicon": settings.favicon,
            "app_icon": settings.app_icon,
            "admin_ids": settings.admin_ids or "",
            "admin_email": settings.admin_email or "",
            "enable_reactions": settings.enable_reactions is not False,
        }


@router.post("/admin/settings")
def api_admin_update_settings(request: Request,
                               server_name: str = Form("WRIT"),
                               server_description: str = Form(""),
                               logo: str = Form(""),
                               favicon: str = Form(""),
                               app_icon: str = Form(""),
                               admin_ids: str = Form(""),
                               admin_email: str = Form(""),
                               enable_reactions: bool = Form(False)):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if len(server_name) > 20:
        raise HTTPException(status_code=400, detail="서버명은 20자 이하여야 합니다.")
    with get_session() as s:
        storage = get_storage()
        settings = ServerSetting.get(s)
        if server_name.strip():
            settings.server_name = server_name[:20]
        settings.server_description = server_description[:500] if server_description else ""
        if (logo and settings.logo and logo != settings.logo) or (not logo and settings.logo):
            storage.delete(settings.logo)
        if favicon and settings.favicon and favicon != settings.favicon:
            storage.delete(settings.favicon)
        elif not favicon and settings.favicon:
            storage.delete(settings.favicon)
            _delete_favicon()
        settings.logo = logo
        settings.favicon = favicon
        if favicon:
            _save_favicon(favicon)
        if app_icon and settings.app_icon and app_icon != settings.app_icon:
            storage.delete(settings.app_icon)
        elif not app_icon and settings.app_icon:
            storage.delete(settings.app_icon)
            _delete_pwa_icons()
        settings.app_icon = app_icon
        if app_icon:
            _save_pwa_icons(app_icon)
        settings.admin_ids = admin_ids
        settings.admin_email = admin_email
        settings.enable_reactions = enable_reactions
        s.commit()
    log_admin_action(user.id, user.username, "update_settings", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.get("/admin/logs")
def api_admin_logs(request: Request, action: str = "", target_type: str = "", target_username: str = "", target_id: int = 0, offset: int = 0, limit: int = 50):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        q = s.query(AdminLog).order_by(AdminLog.created_at.desc())
        if action:
            q = q.filter(AdminLog.action == action)
        if target_type:
            q = q.filter(AdminLog.target_type == target_type)
        if target_username:
            q = q.filter(AdminLog.target_username == target_username)
        if target_id:
            q = q.filter(AdminLog.target_id == target_id)
        total = q.count()
        rows = q.offset(offset).limit(limit + 1).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {
            "logs": [{
                "id": r.id,
                "username": r.username,
                "user_id": r.user_id,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "target_username": r.target_username,
                "details": r.details,
                "ip_address": r.ip_address,
                "created_at": _fmt_dt(r.created_at),
            } for r in rows],
            "total": total,
            "has_more": has_more,
        }


__all__ = ["router"]
