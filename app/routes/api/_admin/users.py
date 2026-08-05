"Users management (list/detail/moderate) admin endpoints."

import os
import json
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Form, HTTPException, Query
from sqlalchemy import String

from app.models import User, Post, Follow, Novel, Notification
from app.serializers import _user_json
from app.config.settings import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
from app.core.activitypub import _resolve_actor, _fetch_remote_count
from app.core.timeline_stream import broadcast_refresh_notifs
from app.core.auth import require_auth, hash_password
from app.utils.log import log_admin_action
from app.db.database import get_session

import logging
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/admin/stats")
def api_admin_stats(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        users = s.query(User).filter_by(is_remote=False).count()
        posts = s.query(Post).filter_by(is_deleted=False).count()
        series = s.query(Novel).count()
        return {"users": users, "posts": posts, "series": series}


@router.get("/admin/users")
def api_admin_users(request: Request, location: str = Query("local"), status: str = Query("all"),
                     role: str = Query("all"), sort: str = Query("newest"),
                     q: str = Query(""), username_q: str = Query(""), name_q: str = Query(""),
                     email_q: str = Query(""), ip_q: str = Query(""), domain_q: str = Query("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        qb = s.query(User)
        if location == "local":
            qb = qb.filter_by(is_remote=False)
        elif location == "remote":
            qb = qb.filter_by(is_remote=True)
        if status == "active":
            qb = qb.filter(User.is_suspended == False, User.is_remote == False)
        elif status == "suspended":
            qb = qb.filter(User.is_suspended == True)
        elif status == "pending":
            qb = qb.filter(User.email_verified == False, User.is_remote == False)
        elif status == "inactive":
            # no recent activity > 30 days (local only)
            cutoff = datetime.utcnow() - timedelta(days=30)
            qb = qb.filter(User.is_remote == False, User.created_at < cutoff)
        if role == "admin":
            qb = qb.filter(User.role.in_(["admin", "owner"]))
        elif role == "moderator":
            qb = qb.filter(User.role == "moderator")
        elif role == "owner":
            qb = qb.filter(User.role == "owner")
        elif role == "user":
            qb = qb.filter(User.role == "user")
        if q:
            pattern = f"%{q}%"
            qb = qb.filter(
                User.username.ilike(pattern) |
                User.display_name.ilike(pattern) |
                User.email.ilike(pattern) |
                User.recent_ips.cast(String).ilike(pattern)
            )
        if username_q:
            qb = qb.filter(User.username.ilike(f"%{username_q}%"))
        if name_q:
            qb = qb.filter(User.display_name.ilike(f"%{name_q}%"))
        if email_q:
            qb = qb.filter(User.email.ilike(f"%{email_q}%"))
        if ip_q:
            qb = qb.filter(User.recent_ips.cast(String).ilike(f"%{ip_q}%"))
        if domain_q:
            qb = qb.filter(User.username.ilike(f"%@{domain_q}%") | User.email.ilike(f"%@{domain_q}%"))
        if sort == "active":
            qb = qb.order_by(User.updated_at.desc())
        else:
            qb = qb.order_by(User.created_at.desc())
        users = qb.limit(50).all()
        result = []
        for u in users:
            post_count = s.query(Post).filter_by(author_id=u.id, is_deleted=False).count()
            follower_count = s.query(Follow).filter_by(following_id=u.id, accepted=True).count()
            recent_post = s.query(Post).filter_by(author_id=u.id).order_by(Post.created_at.desc()).first()
            last_active = str(recent_post.created_at) if recent_post and recent_post.created_at else str(u.created_at) if u.created_at else ""
            email_domain = u.email.split("@")[-1] if "@" in (u.email or "") else ""
            result.append({
                **_user_json(u),
                "created_at": str(u.created_at) if u.created_at else "",
                "post_count": post_count,
                "follower_count": follower_count,
                "last_active": last_active,
                "email_domain": email_domain,
                "recent_ips": (u.recent_ips or [])[:3],
                "is_suspended": getattr(u, 'is_suspended', False),
                "is_frozen": getattr(u, 'is_frozen', False),
                "is_limited": getattr(u, 'is_limited', False),
                "is_deceased": getattr(u, 'is_deceased', False),
            })
        return {"users": result}


@router.get("/admin/users/{user_id}")
def api_admin_user_detail(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        post_count = s.query(Post).filter_by(author_id=u.id, is_deleted=False).count()
        follower_count = s.query(Follow).filter_by(following_id=u.id, accepted=True).count()
        following_count = s.query(Follow).filter_by(follower_id=u.id, accepted=True).count()
        recent_post = s.query(Post).filter_by(author_id=u.id).order_by(Post.created_at.desc()).first()
        last_active = str(recent_post.created_at) if recent_post and recent_post.created_at else str(u.created_at) if u.created_at else ""
        novels = s.query(Novel).filter_by(author_id=u.id).count()
        email_domain = u.email.split("@")[-1] if "@" in (u.email or "") else ""
        return {
            **_user_json(u),
            "created_at": str(u.created_at) if u.created_at else "",
            "post_count": post_count,
            "follower_count": follower_count,
            "following_count": following_count,
            "novels_count": novels,
            "last_active": last_active,
            "email_domain": email_domain,
            "recent_ips": (u.recent_ips or [])[:10],
            "is_limited": getattr(u, 'is_limited', False),
            "is_frozen": getattr(u, 'is_frozen', False),
            "is_deceased": getattr(u, 'is_deceased', False),
            "is_suspended": getattr(u, 'is_suspended', False),
            "is_sensitive": getattr(u, 'is_sensitive', False),
            "moderation_note": getattr(u, 'moderation_note', '') or '',
            "email_verified": getattr(u, 'email_verified', False),
            "summary": u.summary or "",
        }


@router.post("/admin/users/{user_id}/reset-password")
def api_admin_reset_password(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    new_pass = secrets.token_hex(8)
    salt, hsh = hash_password(new_pass)
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        u.password_hash = salt + ":" + hsh
        u.session_token = ""
        target_username = u.username
        s.commit()
    log_admin_action(user.id, user.username, "reset_password", target_type="user", target_id=user_id, target_username=target_username, ip_address=request.client.host if request.client else "")
    return {"ok": True, "new_password": new_pass}


@router.post("/admin/users/{user_id}/change-email")
def api_admin_change_email(request: Request, user_id: int, email: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        old_email = u.email
        u.email = email
        u.email_verified = False
        target_username = u.username
        s.commit()
    log_admin_action(user.id, user.username, "admin_change_email", target_type="user", target_id=user_id, target_username=target_username, details=f"{old_email} -> {email}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/change-role")
def api_admin_change_role(request: Request, user_id: int, role: str = Form("user")):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Only admins can change roles")
    if role not in ("user", "moderator", "admin", "owner"):
        raise HTTPException(status_code=400, detail="Invalid role")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        old_role = u.role
        u.role = role
        u.is_admin = role in ("admin", "owner")
        target_username = u.username
        s.commit()
    log_admin_action(user.id, user.username, "change_role", target_type="user", target_id=user_id, target_username=target_username, details=f"{old_role} -> {role}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/verify-email")
def api_admin_verify_email(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        u.email_verified = True
        s.commit()
        target_username = u.username
    log_admin_action(user.id, user.username, "verify_email", target_type="user", target_id=user_id, target_username=target_username, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/remove-avatar")
def api_admin_remove_avatar(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
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
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
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
    except Exception as e:
        logger.exception("Failed to refresh profile for user %s", user_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/users/suspend")
def api_admin_suspend_users(request: Request, user_ids: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    ids = [int(i) for i in user_ids.split(",") if i.strip()]
    ip = request.client.host if request.client else ""
    with get_session() as s:
        targets = s.query(User).filter(User.id.in_(ids)).all()
        for t in targets:
            t.is_suspended = True
        s.commit()
        target_infos = [(t.id, t.username) for t in targets]
    for t_id, t_username in target_infos:
        log_admin_action(user.id, user.username, "suspend", target_type="user", target_id=t_id, target_username=t_username, ip_address=ip)
    return {"ok": True}


@router.post("/admin/users/unsuspend")
def api_admin_unsuspend_users(request: Request, user_ids: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    ids = [int(i) for i in user_ids.split(",") if i.strip()]
    ip = request.client.host if request.client else ""
    with get_session() as s:
        targets = s.query(User).filter(User.id.in_(ids)).all()
        for t in targets:
            t.is_suspended = False
        s.commit()
        target_infos = [(t.id, t.username) for t in targets]
    for t_id, t_username in target_infos:
        log_admin_action(user.id, user.username, "unsuspend", target_type="user", target_id=t_id, target_username=t_username, ip_address=ip)
    return {"ok": True}


@router.post("/admin/users/{user_id}/note")
def api_admin_user_note(request: Request, user_id: int, note: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u: raise HTTPException(status_code=404, detail="User not found")
        u.moderation_note = note
        target_username = u.username
        s.commit()
    log_admin_action(user.id, user.username, "set_note", target_type="user", target_id=user_id, target_username=target_username, details=note[:200], ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/users/{user_id}/moderate")
def api_admin_moderate(request: Request, user_id: int, action: str = Form(...), send_email: bool = Form(False), message: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    valid_actions = ("warning", "freeze", "unfreeze", "sensitive", "unsensitive", "limit", "unlimit", "suspend", "unsuspend", "deceased", "undeceased")
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u: raise HTTPException(status_code=404, detail="User not found")

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
            except Exception as e:
                logger.exception("Failed to send moderation email to %s", u.email)
    return {"ok": True, "action": action}


@router.post("/admin/users/{user_id}/toggle-sensitive")
def api_admin_toggle_sensitive(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u: raise HTTPException(status_code=404, detail="User not found")
        u.is_sensitive = not u.is_sensitive
        s.commit()
        target_username = u.username
        is_sensitive = u.is_sensitive
    log_admin_action(user.id, user.username, f"toggle_sensitive:{is_sensitive}", target_type="user", target_id=user_id, target_username=target_username, ip_address=request.client.host if request.client else "")
    return {"ok": True, "is_sensitive": is_sensitive}
