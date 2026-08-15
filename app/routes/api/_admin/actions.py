"User moderation/action admin endpoints."

import json
import logging
import os
import secrets
import smtplib
from email.mime.text import MIMEText

from fastapi import APIRouter, Form, HTTPException, Request

from app.config.settings import SMTP_FROM, SMTP_PASSWORD, SMTP_PORT, SMTP_SERVER, SMTP_USER
from app.core.activitypub import _fetch_remote_count, _resolve_actor
from app.core.auth import hash_password
from app.core.permissions import require_permission
from app.core.timeline_stream import broadcast_refresh_notifs
from app.db.database import get_session
from app.models import Notification, Post, Role, User
from app.utils.log import log_admin_action

logger = logging.getLogger(__name__)

router = APIRouter()

_ROLE_PRIORITY = {"user": 0, "moderator": 1, "admin": 2, "owner": 3}


def _guard_target_role(actor: User, target: User):
    """등급이 같거나 높은 대상 계정(오너/관리자/중재자)에 대한 관리 행위를 차단한다."""
    actor_rank = _ROLE_PRIORITY.get(str(actor.role or "user"), 0)
    target_rank = _ROLE_PRIORITY.get(str(target.role or "user"), 0)
    if target_rank >= actor_rank:
        raise HTTPException(status_code=403, detail="상위 또는 동급 계정은 관리할 수 없습니다.")


@router.post("/admin/users/{user_id}/reset-password")
def api_admin_reset_password(request: Request, user_id: int):
    user = require_permission(request, "users.manage")
    new_pass = secrets.token_hex(8)
    salt, hsh = hash_password(new_pass)
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)
        u.password_hash = salt + ":" + hsh
        target_username = u.username
        s.commit()
    from app.core.auth import delete_user_sessions
    delete_user_sessions(user_id)
    log_admin_action(user.id, user.username, "reset_password", target_type="user", target_id=user_id, target_username=target_username, ip_address=request.client.host if request.client else "")
    return {"ok": True, "new_password": new_pass}


@router.post("/admin/users/{user_id}/change-email")
def api_admin_change_email(request: Request, user_id: int, email: str = Form(...)):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)
        old_email = u.email
        u.email = email
        u.email_verified = False
        target_username = u.username
        s.commit()
    log_admin_action(user.id, user.username, "admin_change_email", target_type="user", target_id=user_id, target_username=target_username, details=f"{old_email} -> {email}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/change-role")
def api_admin_change_role(request: Request, user_id: int, role: str = Form("user")):
    user = require_permission(request, "users.admin")
    if role not in ("user", "moderator", "admin", "owner"):
        with get_session() as s:
            exists = s.query(Role).filter_by(name=role).first()
        if not exists:
            raise HTTPException(status_code=400, detail="Invalid role")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)
        old_role = u.role
        u.role = role
        u.is_admin = role in ("admin", "owner")
        target_username = u.username
        s.commit()
    log_admin_action(user.id, user.username, "change_role", target_type="user", target_id=user_id, target_username=target_username, details=f"{old_role} -> {role}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/verify-email")
def api_admin_verify_email(request: Request, user_id: int):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)
        u.email_verified = True
        s.commit()
        target_username = u.username
    log_admin_action(user.id, user.username, "verify_email", target_type="user", target_id=user_id, target_username=target_username, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/remove-avatar")
def api_admin_remove_avatar(request: Request, user_id: int):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)
        old = u.profile_image
        u.profile_image = ""
        s.commit()
        if old:
            old_path = old.lstrip("/")
            if os.path.isfile(old_path):
                os.remove(old_path)
        target_username = u.username
    log_admin_action(user.id, user.username, "remove_avatar", target_type="user", target_id=user_id, target_username=target_username, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/refresh-profile")
def api_admin_refresh_profile(request: Request, user_id: int):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)
        if not u.is_remote or not u.remote_url:
            raise HTTPException(status_code=400, detail="Not a remote user or no remote_url")
        remote_url = u.remote_url
    try:
        actor = _resolve_actor(remote_url, force_refresh=True, sign_as=user)
        if not actor:
            raise HTTPException(status_code=400, detail="Failed to refresh profile")
        _fc = _fetch_remote_count(remote_url.rstrip("/") + "/followers", user)
        _fg = _fetch_remote_count(remote_url.rstrip("/") + "/following", user)
        with get_session() as _s2:
            _reloaded = _s2.query(User).get(actor.id)
            if _reloaded:
                _reloaded.remote_followers_count = _fc
                _reloaded.remote_following_count = _fg
                _s2.commit()
            _name = _reloaded.display_name if _reloaded else ""
            _username = _reloaded.username if _reloaded else ""
        log_admin_action(user.id, user.username, "refresh_profile", target_type="user", target_id=user_id, target_username=_username, ip_address=request.client.host if request.client else "")
        return {"ok": True, "display_name": _name}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to refresh profile for user %s", user_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/admin/users/suspend")
def api_admin_suspend_users(request: Request, user_ids: str = Form(...)):
    user = require_permission(request, "users.manage")
    ids = [int(i) for i in user_ids.split(",") if i.strip()]
    ip = request.client.host if request.client else ""
    with get_session() as s:
        targets = s.query(User).filter(User.id.in_(ids)).all()
        for t in targets:
            _guard_target_role(user, t)
        for t in targets:
            t.is_suspended = True
        s.commit()
        target_infos = [(t.id, t.username) for t in targets]
    for t_id, t_username in target_infos:
        log_admin_action(user.id, user.username, "suspend", target_type="user", target_id=t_id, target_username=t_username, ip_address=ip)
    return {"ok": True}


@router.post("/admin/users/unsuspend")
def api_admin_unsuspend_users(request: Request, user_ids: str = Form(...)):
    user = require_permission(request, "users.manage")
    ids = [int(i) for i in user_ids.split(",") if i.strip()]
    ip = request.client.host if request.client else ""
    with get_session() as s:
        targets = s.query(User).filter(User.id.in_(ids)).all()
        for t in targets:
            _guard_target_role(user, t)
        for t in targets:
            t.is_suspended = False
        s.commit()
        target_infos = [(t.id, t.username) for t in targets]
    for t_id, t_username in target_infos:
        log_admin_action(user.id, user.username, "unsuspend", target_type="user", target_id=t_id, target_username=t_username, ip_address=ip)
    return {"ok": True}


@router.post("/admin/users/{user_id}/note")
def api_admin_user_note(request: Request, user_id: int, note: str = Form("")):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)
        u.moderation_note = note
        target_username = u.username
        s.commit()
    log_admin_action(user.id, user.username, "set_note", target_type="user", target_id=user_id, target_username=target_username, details=note[:200], ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/moderate")
def api_admin_moderate(request: Request, user_id: int, action: str = Form(...), send_email: bool = Form(False), message: str = Form("")):
    user = require_permission(request, "users.manage")
    valid_actions = ("warning", "freeze", "unfreeze", "sensitive", "unsensitive", "limit", "unlimit", "suspend", "unsuspend", "deceased", "undeceased")
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)

        if action == "warning":
            pass  # Just a warning, no automatic action
        elif action == "freeze":
            u.is_frozen = True
            u.is_suspended = False
        elif action == "unfreeze":
            u.is_frozen = False
        elif action == "sensitive":
            u.is_sensitive = True
        elif action == "unsensitive":
            u.is_sensitive = False
        elif action == "limit":
            u.is_limited = True
            u.is_sensitive = True
            u.is_suspended = False
            for p in s.query(Post).filter(Post.author_id == u.id, Post.visibility == "public").all():
                p.original_visibility = p.visibility
                p.visibility = "home"
        elif action == "suspend":
            u.is_suspended = True
            _suspend_notif_users = set()
            for p in s.query(Post).filter(Post.author_id == u.id).all():
                s.query(Post).filter(Post.in_reply_to_id == p.id).update({"in_reply_to_id": None})
                for _n in s.query(Notification.user_id).filter(Notification.post_id == p.id).distinct().all():
                    _suspend_notif_users.add(_n[0])
                s.query(Notification).filter(Notification.post_id == p.id).delete()
                s.delete(p)
        elif action == "unlimit":
            u.is_limited = False
            u.is_sensitive = False
            for p in s.query(Post).filter(Post.author_id == u.id, Post.original_visibility != "").all():
                p.visibility = p.original_visibility
                p.original_visibility = ""
        elif action == "unsuspend":
            u.is_suspended = False
            u.is_limited = False
            for p in s.query(Post).filter(Post.author_id == u.id, Post.original_visibility != "").all():
                p.visibility = p.original_visibility
                p.original_visibility = ""
        elif action == "deceased":
            u.is_deceased = True
        elif action == "undeceased":
            u.is_deceased = False

        # Create notification for the moderated user
        notif = Notification(
            user_id=u.id,
            from_user_id=user.id,
            notification_type="moderation",
            metadata_json=json.dumps({"action": action, "message": message}, ensure_ascii=False),
        )
        s.add(notif)
        s.commit()
        try:
            for _uid in _suspend_notif_users:
                broadcast_refresh_notifs(_uid)
        except Exception:
            pass
        log_admin_action(user.id, user.username, f"moderate:{action}", target_type="user", target_id=user_id, target_username=u.username, details=message or "", ip_address=request.client.host if request.client else "")

        if send_email and u.email:
            try:
                if not SMTP_SERVER:
                    return {"ok": True, "action": action}
                action_names = {"warning": "경고", "freeze": "동결", "sensitive": "민감 처리", "limit": "제한", "suspend": "정지", "unsuspend": "정지 해제"}
                msg = MIMEText(f"계정에 {action_names.get(action, action)} 조치가 적용되었습니다.\n서버 관리팀")
                msg["Subject"] = f"[WRIT] 계정 {action_names.get(action, action)} 안내"
                msg["From"] = SMTP_FROM or "noreply@writ.local"
                msg["To"] = u.email
                port = SMTP_PORT or 587
                if port == 465:
                    with smtplib.SMTP_SSL(SMTP_SERVER, port, timeout=10) as smtp:
                        if SMTP_USER:
                            smtp.login(SMTP_USER, SMTP_PASSWORD or "")
                        smtp.send_message(msg)
                else:
                    with smtplib.SMTP(SMTP_SERVER, port, timeout=10) as smtp:
                        smtp.ehlo()
                        if smtp.has_extn("STARTTLS"):
                            smtp.starttls()
                            smtp.ehlo()
                        if SMTP_USER:
                            smtp.login(SMTP_USER, SMTP_PASSWORD or "")
                        smtp.send_message(msg)
            except Exception:
                logger.exception("Failed to send moderation email to %s", u.email)
    return {"ok": True, "action": action}


@router.post("/admin/users/{user_id}/toggle-sensitive")
def api_admin_toggle_sensitive(request: Request, user_id: int):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _guard_target_role(user, u)
        u.is_sensitive = not u.is_sensitive
        s.commit()
        target_username = u.username
        is_sensitive = u.is_sensitive
    log_admin_action(user.id, user.username, f"toggle_sensitive:{is_sensitive}", target_type="user", target_id=user_id, target_username=target_username, ip_address=request.client.host if request.client else "")
    return {"ok": True, "is_sensitive": is_sensitive}
