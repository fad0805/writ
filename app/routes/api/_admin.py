"""Admin API endpoints extracted from api.py."""

import os
import re
import io
import json
import logging
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request, Form, HTTPException, Query, Depends
from PIL import Image
from sqlalchemy import desc, or_, and_, func, String
from sqlalchemy.orm import joinedload, selectinload

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, Tag, CustomEmoji, Report, ServerRule, BlockedDomain, FederationBlock, AllowedServer, MutedServer, ServerSetting, AdminLog
from app.serializers import _user_json
from app.config.settings import BASE_URL, SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
from app.core.activitypub import _resolve_actor, _send_flag, _fetch_remote_count
from app.core.timeline_stream import broadcast_refresh_notifs
from app.db.database import get_session
from app.routes.auth import require_auth, hash_password
from app.utils.datetime import _fmt_dt
from app.utils.log import log_admin_action
from app.utils.storage import get_storage

from app.routes.api._core import _read_storage_file, _save_pwa_icons, _save_favicon, _delete_favicon, _delete_pwa_icons
from app.routes.api._series import _novel_json, _apply_latest_activity_order

logger = logging.getLogger(__name__)

admin_router = APIRouter()


def _domain_users(s, domain):
    """Return all remote User objects whose remote_url hostname matches domain."""
    candidates = s.query(User).filter(
        User.is_remote == True,
        or_(
            User.remote_url.like(f"https://{domain}/%"),
            User.remote_url.like(f"http://{domain}/%"),
        )
    ).all()
    result = []
    for u in candidates:
        if u.remote_url:
            parsed = urlparse(u.remote_url)
            if parsed.hostname == domain:
                result.append(u)
    return result


@admin_router.get("/admin/stats")
def api_admin_stats(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        users = s.query(User).filter_by(is_remote=False).count()
        posts = s.query(Post).filter_by(is_deleted=False).count()
        series = s.query(Novel).count()
        return {"users": users, "posts": posts, "series": series}


@admin_router.get("/admin/users")
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


@admin_router.get("/admin/users/{user_id}")
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


@admin_router.post("/admin/users/{user_id}/reset-password")
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


@admin_router.post("/admin/users/{user_id}/change-email")
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


@admin_router.post("/admin/users/{user_id}/change-role")
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


@admin_router.post("/admin/users/{user_id}/verify-email")
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


@admin_router.post("/admin/users/{user_id}/remove-avatar")
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


@admin_router.post("/admin/users/{user_id}/refresh-profile")
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


@admin_router.post("/admin/users/suspend")
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


@admin_router.post("/admin/users/unsuspend")
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


@admin_router.post("/admin/users/{user_id}/note")
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


@admin_router.post("/admin/users/{user_id}/moderate")
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


@admin_router.post("/admin/users/{user_id}/toggle-sensitive")
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


@admin_router.get("/admin/content/search")
def api_admin_content_search(request: Request, q: str = "", mode: str = "series"):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not q.strip():
        return {"novels": [], "episodes": []}
    with get_session() as s:
        query = q.strip()
        like = f"%{query}%"
        if mode == "episode":
            episodes = s.query(Episode).options(joinedload(Episode.novel)).filter(
                Episode.title.ilike(like)
            ).order_by(desc(Episode.created_at)).limit(50).all()
            return {"novels": [], "episodes": [{
                "id": ep.id, "title": ep.title, "number": ep.episode_number, "is_published": ep.is_published,
                "created_at": _fmt_dt(ep.created_at), "novel_id": ep.novel_id,
            } for ep in episodes]}
        else:
            novels_q = s.query(Novel).options(selectinload(Novel.author))
            if re.match(r'^\d+$', query):
                novels_q = novels_q.filter(
                    or_(Novel.title.ilike(like), Novel.id == int(query))
                )
            elif re.match(r'^[a-f0-9]{6,16}$', query):
                novels_q = novels_q.filter(
                    or_(Novel.title.ilike(like), Novel.number == query)
                )
            else:
                novels_q = novels_q.filter(Novel.title.ilike(like))
            novels = _apply_latest_activity_order(novels_q, s).limit(50).all()
            novel_ids = [n.id for n in novels]
            episodes = s.query(Episode).filter(
                Episode.novel_id.in_(novel_ids)
            ).order_by(desc(Episode.created_at)).all()
            ep_map: dict[int, list] = {}
            for ep in episodes:
                ep_map.setdefault(ep.novel_id, []).append({
                    "id": ep.id, "title": ep.title, "number": ep.episode_number, "is_published": ep.is_published,
                    "created_at": _fmt_dt(ep.created_at), "novel_id": ep.novel_id,
                })
            result = []
            for n in novels:
                nj = _novel_json(n, s)
                nj["episodes"] = ep_map.get(n.id, [])
                result.append(nj)
            return {"novels": result, "episodes": []}

@admin_router.post("/admin/novels/{novel_id}/toggle-sensitive")
def api_admin_toggle_novel_sensitive(request: Request, novel_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        n = s.query(Novel).get(novel_id)
        if not n: raise HTTPException(status_code=404, detail="Novel not found")
        new_val = not (n.is_sensitive or False)
        s.query(Novel).filter_by(id=novel_id).update(
            {"is_sensitive": new_val}, synchronize_session=False
        )
        s.commit()
    return {"ok": True, "is_sensitive": new_val}


@admin_router.post("/admin/novels/{novel_id}/set-visibility")
def api_admin_set_novel_visibility(request: Request, novel_id: int, visibility: str = Form("public")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if visibility not in ("public", "unlisted", "private"):
        raise HTTPException(status_code=400, detail="Invalid visibility")
    with get_session() as s:
        n = s.query(Novel).get(novel_id)
        if not n: raise HTTPException(status_code=404, detail="Novel not found")
        is_published = visibility != "private"
        s.query(Novel).filter_by(id=novel_id).update(
            {"visibility": visibility, "is_published": is_published},
            synchronize_session=False
        )
        s.commit()
    return {"ok": True, "visibility": visibility}


@admin_router.post("/admin/episodes/{episode_id}/toggle-publish")
def api_admin_toggle_episode_publish(request: Request, episode_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        ep = s.query(Episode).get(episode_id)
        if not ep: raise HTTPException(status_code=404, detail="Episode not found")
        new_val = not ep.is_published
        s.query(Episode).filter_by(id=episode_id).update(
            {"is_published": new_val}, synchronize_session=False
        )
        s.commit()
        log_admin_action(user.id, user.username, "toggle_episode_publish", target_type="episode", target_id=episode_id, target_username=ep.novel.author.username if ep.novel else "", details=f"published={new_val}", ip_address=request.client.host if request.client else "")
    return {"ok": True, "is_published": new_val}


@admin_router.get("/admin/reports")
def api_admin_list_reports(request: Request, status: str = "pending", target_type: str = "", offset: int = 0, limit: int = 50):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        q = s.query(Report)
        if status in ("pending", "resolved", "dismissed"):
            q = q.filter(Report.status == status)
        if target_type in ("post", "novel", "episode"):
            q = q.filter(Report.target_type == target_type)
        total = q.count()
        reports = q.order_by(Report.created_at.desc()).offset(offset).limit(limit).all()
        results = []
        for r in reports:
            item = {
                "id": r.id,
                "reporter": {"id": r.reporter.id, "username": r.reporter.username, "display_name": r.reporter.display_name},
                "target_type": r.target_type,
                "target_id": r.target_id,
                "reason": r.reason,
                "rule_ids": r.rule_ids if r.rule_ids else [],
                "status": r.status,
                "created_at": _fmt_dt(r.created_at),
            }
            if r.rule_ids:
                rules = s.query(ServerRule).filter(ServerRule.id.in_(r.rule_ids)).all()
                item["rules"] = [{"id": rule.id, "title": rule.title} for rule in rules]
            if r.target_type == "post":
                post = s.query(Post).filter_by(id=r.target_id).first()
                if post:
                    item["target"] = {
                        "id": post.id,
                        "content": post.content[:200] if post.content else "",
                        "author": {"id": post.author.id, "username": post.author.username, "display_name": post.author.display_name},
                        "is_deleted": post.is_deleted,
                    }
            elif r.target_type == "novel":
                novel = s.query(Novel).filter_by(id=r.target_id).first()
                if novel:
                    item["target"] = {
                        "id": novel.id,
                        "title": novel.title,
                        "author": {"id": novel.author.id, "username": novel.author.username, "display_name": novel.author.display_name},
                    }
            elif r.target_type == "episode":
                ep = s.query(Episode).filter_by(id=r.target_id).first()
                if ep:
                    item["target"] = {
                        "id": ep.id,
                        "title": ep.title,
                        "novel_id": ep.novel_id,
                        "novel_title": ep.novel.title if ep.novel else "",
                        "author": {"id": ep.novel.author.id, "username": ep.novel.author.username, "display_name": ep.novel.author.display_name} if ep.novel else None,
                    }
            if r.resolved_by_id:
                resolver = s.query(User).filter_by(id=r.resolved_by_id).first()
                if resolver:
                    item["resolved_by"] = {"id": resolver.id, "username": resolver.username}
            results.append(item)
        return {"reports": results, "total": total}


@admin_router.get("/admin/reports/{report_id}")
def api_admin_get_report(request: Request, report_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        r = s.query(Report).get(report_id)
        if not r:
            raise HTTPException(status_code=404, detail="Report not found")
        item = {
            "id": r.id,
            "reporter": {"id": r.reporter.id, "username": r.reporter.username, "display_name": r.reporter.display_name},
            "target_type": r.target_type,
            "target_id": r.target_id,
            "reason": r.reason,
            "rule_ids": r.rule_ids if r.rule_ids else [],
            "status": r.status,
            "created_at": _fmt_dt(r.created_at),
        }
        if r.rule_ids:
            rules = s.query(ServerRule).filter(ServerRule.id.in_(r.rule_ids)).all()
            item["rules"] = [{"id": rule.id, "title": rule.title, "description": rule.description} for rule in rules]
        if r.target_type == "post":
            post = s.query(Post).filter_by(id=r.target_id).first()
            if post:
                item["target"] = {
                    "id": post.id,
                    "content": post.content,
                    "summary": post.summary or "",
                    "author": {"id": post.author.id, "username": post.author.username, "display_name": post.author.display_name, "is_remote": post.author.is_remote},
                    "is_deleted": post.is_deleted,
                    "author_id": post.author_id,
                }
        elif r.target_type == "novel":
            novel = s.query(Novel).filter_by(id=r.target_id).first()
            if novel:
                item["target"] = {
                    "id": novel.id,
                    "title": novel.title,
                    "description": novel.description,
                    "author": {"id": novel.author.id, "username": novel.author.username, "display_name": novel.author.display_name, "is_remote": novel.author.is_remote},
                    "author_id": novel.author_id,
                }
        elif r.target_type == "episode":
            ep = s.query(Episode).filter_by(id=r.target_id).first()
            if ep and ep.novel:
                item["target"] = {
                    "id": ep.id,
                    "title": ep.title,
                    "content": ep.content[:500],
                    "novel_id": ep.novel_id,
                    "novel_title": ep.novel.title,
                    "author": {"id": ep.novel.author.id, "username": ep.novel.author.username, "display_name": ep.novel.author.display_name, "is_remote": ep.novel.author.is_remote},
                    "author_id": ep.novel.author_id,
                }
        if r.resolved_by_id:
            resolver = s.query(User).filter_by(id=r.resolved_by_id).first()
            if resolver:
                item["resolved_by"] = {"id": resolver.id, "username": resolver.username}
        return item


@admin_router.post("/admin/reports/{report_id}/resolve")
def api_admin_resolve_report(request: Request, report_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        report = s.query(Report).get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        report.status = "resolved"
        report.resolved_by_id = user.id
        s.commit()
        r_type, r_id = report.target_type, report.target_id
    log_admin_action(user.id, user.username, "resolve_report", target_type="report", target_id=report_id, details=f"target:{r_type}:{r_id}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.post("/admin/reports/{report_id}/dismiss")
def api_admin_dismiss_report(request: Request, report_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        report = s.query(Report).get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        report.status = "dismissed"
        report.resolved_by_id = user.id
        s.commit()
        r_type, r_id = report.target_type, report.target_id
    log_admin_action(user.id, user.username, "dismiss_report", target_type="report", target_id=report_id, details=f"target:{r_type}:{r_id}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.post("/admin/reports/{report_id}/forward")
def api_admin_forward_report(request: Request, report_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        report = s.query(Report).get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        target_obj = None
        if report.target_type == "post":
            target_obj = s.query(Post).get(report.target_id)
        if not target_obj or not hasattr(target_obj, 'author') or not target_obj.author or not target_obj.author.is_remote:
            raise HTTPException(status_code=400, detail="Target not remote")
        reporter = s.query(User).get(report.reporter_id)
        if not reporter:
            raise HTTPException(status_code=400, detail="Reporter not found")
        try:
            _send_flag(reporter, report.target_type, target_obj, report.reason[:200], report.rule_ids or [])
        except Exception as e:
            logger.error("Failed to forward report %s: %s", report_id, e)
            raise HTTPException(status_code=500, detail="Failed to forward report")
    return {"ok": True}

@admin_router.get("/admin/rules")
def api_admin_list_rules(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        rules = s.query(ServerRule).order_by(ServerRule.sort_order).all()
        return [{"id": r.id, "title": r.title, "description": r.description, "sort_order": r.sort_order} for r in rules]


@admin_router.post("/admin/rules/new")
def api_admin_create_rule(request: Request, title: str = Form(...), description: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        max_order = s.query(func.max(ServerRule.sort_order)).scalar() or 0
        rule = ServerRule(title=title, description=description, sort_order=max_order + 1)
        s.add(rule)
        s.commit()
        return {"id": rule.id, "title": rule.title, "description": rule.description, "sort_order": rule.sort_order}


@admin_router.post("/admin/rules/{rule_id}/edit")
def api_admin_edit_rule(request: Request, rule_id: int, title: str = Form(...), description: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        rule = s.query(ServerRule).get(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        rule.title = title
        rule.description = description
        s.commit()
        return {"id": rule.id, "title": rule.title, "description": rule.description, "sort_order": rule.sort_order}


@admin_router.post("/admin/rules/{rule_id}/delete")
def api_admin_delete_rule(request: Request, rule_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        rule = s.query(ServerRule).get(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        s.delete(rule)
        s.commit()
    return {"ok": True}


@admin_router.post("/admin/rules/reorder")
def api_admin_reorder_rules(request: Request, rule_ids: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    ids = []
    try:
        ids = json.loads(rule_ids)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid rule_ids")
    with get_session() as s:
        for i, rid in enumerate(ids):
            s.query(ServerRule).filter_by(id=rid).update({"sort_order": i})
        s.commit()
    return {"ok": True}


@admin_router.post("/admin/posts/{post_id}/set-cw")
def api_admin_set_post_cw(request: Request, post_id: int, summary: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        tag = "[관리자 강제] "
        if not summary:
            summary = "규칙 위반 게시글"
        if not summary.startswith(tag):
            summary = tag + summary
        post.summary = summary
        s.commit()
        author_username = post.author.username
    log_admin_action(user.id, user.username, "set_post_cw", target_type="post", target_id=post_id, target_username=f"@{author_username}", details=summary, ip_address=request.client.host if request.client else "")
    return {"ok": True, "summary": summary}


@admin_router.post("/admin/posts/{post_id}/remove-cw")
def api_admin_remove_post_cw(request: Request, post_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.summary = ""
        s.commit()
        author_username = post.author.username
    log_admin_action(user.id, user.username, "remove_post_cw", target_type="post", target_id=post_id, target_username=f"@{author_username}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.get("/admin/blocked-domains")
def api_admin_list_blocked_domains(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        domains = s.query(BlockedDomain).order_by(BlockedDomain.created_at.desc()).all()
        return {"domains": [{
            "id": d.id,
            "domain": d.domain,
            "created_by": d.created_by.username if d.created_by else "",
            "created_at": str(d.created_at) if d.created_at else "",
        } for d in domains]}


@admin_router.post("/admin/block-domain")
def api_admin_block_domain(request: Request, domain: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    with get_session() as s:
        existing = s.query(BlockedDomain).filter_by(domain=domain).first()
        if existing:
            raise HTTPException(status_code=400, detail="Already blocked")
        s.add(BlockedDomain(domain=domain, created_by_id=user.id))
        s.commit()
    log_admin_action(user.id, user.username, "block_domain", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True, "domain": domain}


@admin_router.delete("/admin/block-domain/{domain}")
def api_admin_unblock_domain(request: Request, domain: str):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    with get_session() as s:
        bd = s.query(BlockedDomain).filter_by(domain=domain).first()
        if not bd:
            raise HTTPException(status_code=404, detail="Domain not blocked")
        s.delete(bd)
        s.commit()
    log_admin_action(user.id, user.username, "unblock_domain", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.get("/admin/federation-blocks")
def api_admin_list_federation_blocks(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        blocks = s.query(FederationBlock).order_by(FederationBlock.created_at.desc()).all()
        return {"blocks": [{"id": b.id, "domain": b.domain, "reason": b.reason or "", "created_by": b.created_by.username if b.created_by else "", "created_at": str(b.created_at) if b.created_at else ""} for b in blocks]}


@admin_router.post("/admin/federation-block")
def api_admin_add_federation_block(request: Request, domain: str = Form(...), reason: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    with get_session() as s:
        existing = s.query(FederationBlock).filter_by(domain=domain).first()
        if existing:
            raise HTTPException(status_code=400, detail="Already blocked")
        s.add(FederationBlock(domain=domain, reason=reason, created_by_id=user.id))
        # Also remove from allowed list if present
        s.query(AllowedServer).filter_by(domain=domain).delete()
        s.commit()
    log_admin_action(user.id, user.username, "federation_block", target_type="domain", target_username=domain, details=reason, ip_address=request.client.host if request.client else "")
    return {"ok": True, "domain": domain}


@admin_router.delete("/admin/federation-block/{domain}")
def api_admin_remove_federation_block(request: Request, domain: str):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    with get_session() as s:
        b = s.query(FederationBlock).filter_by(domain=domain).first()
        if not b:
            raise HTTPException(status_code=404, detail="Domain not blocked")
        s.delete(b)
        s.commit()
    log_admin_action(user.id, user.username, "federation_unblock", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.get("/admin/allowed-servers")
def api_admin_list_allowed_servers(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        servers = s.query(AllowedServer).order_by(AllowedServer.created_at.desc()).all()
        return {"servers": [{"id": sv.id, "domain": sv.domain, "created_by": sv.created_by.username if sv.created_by else "", "created_at": str(sv.created_at) if sv.created_at else ""} for sv in servers]}


@admin_router.post("/admin/allowed-server")
def api_admin_add_allowed_server(request: Request, domain: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    with get_session() as s:
        existing = s.query(AllowedServer).filter_by(domain=domain).first()
        if existing:
            raise HTTPException(status_code=400, detail="Already allowed")
        # Also remove from block list if present
        s.query(FederationBlock).filter_by(domain=domain).delete()
        s.add(AllowedServer(domain=domain, created_by_id=user.id))
        s.commit()
    log_admin_action(user.id, user.username, "federation_allow", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True, "domain": domain}


@admin_router.delete("/admin/allowed-server/{domain}")
def api_admin_remove_allowed_server(request: Request, domain: str):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    with get_session() as s:
        sv = s.query(AllowedServer).filter_by(domain=domain).first()
        if not sv:
            raise HTTPException(status_code=404, detail="Domain not allowed")
        s.delete(sv)
        s.commit()
    log_admin_action(user.id, user.username, "federation_disallow", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.get("/admin/remote-servers")
def api_admin_remote_servers(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        remote_users = s.query(User).filter(User.is_remote == True).all()
        domains = set()
        for u in remote_users:
            if u.remote_url:
                domain = urlparse(u.remote_url).hostname
                if domain:
                    domains.add(domain)
        return {"servers": sorted(domains)}


@admin_router.get("/admin/remote-server/{domain:path}")
def api_admin_remote_server(domain: str, request: Request, offset: int = 0, limit: int = 20):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        candidates = s.query(User).filter(
            User.is_remote == True,
            or_(
                User.remote_url.like(f"https://{domain}/%"),
                User.remote_url.like(f"http://{domain}/%"),
            )
        ).all()
        domain_users = []
        for u in candidates:
            if u.remote_url:
                parsed = urlparse(u.remote_url)
                if parsed.hostname == domain:
                    domain_users.append(u)

        total_users = len(domain_users)
        remote_ids = [u.id for u in domain_users]

        local_following = 0
        local_followers = 0
        if remote_ids:
            local_following = s.query(Follow).filter(
                Follow.following_id.in_(remote_ids),
                Follow.accepted == True
            ).count()
            local_followers = s.query(Follow).filter(
                Follow.follower_id.in_(remote_ids),
                Follow.accepted == True
            ).count()

        is_blocked = s.query(FederationBlock).filter_by(domain=domain).first() is not None
        mute_entry = s.query(MutedServer).filter_by(domain=domain).first()
        is_muted = mute_entry is not None and mute_entry.muted
        is_media_muted = mute_entry is not None and mute_entry.media_muted

        try:
            resp = httpx.get(f"https://{domain}", timeout=5)
            is_reachable = resp.status_code < 500
        except:
            is_reachable = False

        paged = domain_users[offset:offset + limit + 1]
        has_more = len(paged) > limit
        paged = paged[:limit]

        return {
            "domain": domain,
            "total_users": total_users,
            "local_following": local_following,
            "local_followers": local_followers,
            "is_reachable": is_reachable,
            "is_blocked": is_blocked,
            "is_muted": is_muted,
            "is_media_muted": is_media_muted,
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "profile_image": u.profile_image,
                    "remote_url": u.remote_url,
                }
                for u in paged
            ],
            "has_more": has_more,
            "total_users_count": total_users,
            "server_icon": f"https://{domain}/favicon.ico",
        }


@admin_router.get("/admin/federation-search")
def api_admin_federation_search(request: Request, q: str = ""):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    q = q.strip()
    logger.info("federation-search q=%r", q)
    if not q:
        return {"results": []}
    results = []
    # Try @handle@domain pattern
    if q.startswith("@") and "@" in q[1:]:
        parts = q[1:].split("@", 1)
        if len(parts) == 2:
            handle = parts[0].strip()
            domain = parts[1].strip()
            logger.info("federation-search handle=%r domain=%r", handle, domain)
            if not handle or not domain:
                return {"results": []}
            local_username = f"{handle}@{domain}"
            with get_session() as s:
                # Check remote users by exact match on username
                remote_user = s.query(User).filter(
                    User.username == local_username,
                    User.is_remote == True,
                ).first()
                logger.info("federation-search exact=%s id=%s", remote_user is not None, getattr(remote_user, 'id', None))
                if not remote_user:
                    remote_user = s.query(User).filter(
                        func.lower(User.username) == local_username.lower(),
                        User.is_remote == True,
                    ).first()
                    logger.info("federation-search casefold=%s id=%s", remote_user is not None, getattr(remote_user, 'id', None))
                if not remote_user:
                    all_remote = s.query(User).filter(
                        User.is_remote == True,
                        User.remote_url.isnot(None),
                    ).limit(500).all()
                    logger.info("federation-search scanning %d remote users for domain=%s handle=%s", len(all_remote), domain, handle)
                    for u in all_remote:
                        parsed = urlparse(u.remote_url)
                        if parsed.hostname and parsed.hostname.lower() == domain.lower():
                            uname = u.username.split("@")[0]
                            if uname.lower() == handle.lower():
                                remote_user = u
                                logger.info("federation-search found by url match: id=%s username=%s", u.id, u.username)
                                break
                if remote_user:
                    results.append({
                        "source": "remote_cached",
                        "id": remote_user.id,
                        "username": remote_user.username,
                        "display_name": remote_user.display_name,
                        "profile_image": remote_user.profile_image,
                        "remote_url": remote_user.remote_url,
                    })
                else:
                    # Try to resolve via ActivityPub
                    # Try actor URL patterns
                    actor_urls = [
                        f"https://{domain}/users/{handle}",
                        f"https://{domain}/@{handle}",
                        f"https://{domain}/u/{handle}",
                        f"https://{domain}/profile/{handle}",
                    ]
                    resolved = None
                    for url in actor_urls:
                        try:
                            resolved = _resolve_actor(url)
                            if resolved:
                                break
                        except Exception:
                            continue
                    if not resolved:
                        # Try WebFinger discovery
                        try:
                            wf = httpx.get(
                                f"https://{domain}/.well-known/webfinger?resource=acct:{handle}@{domain}",
                                timeout=5,
                            )
                            if wf.status_code == 200:
                                wf_data = wf.json()
                                for link in wf_data.get("links", []):
                                    if link.get("rel") == "self" and link.get("type", "").endswith("activity+json"):
                                        href = link.get("href", "")
                                        if href:
                                            resolved = _resolve_actor(href)
                                            break
                        except Exception:
                            pass
                    if resolved:
                        results.append({
                            "source": "remote_fetched",
                            "id": resolved.id,
                            "username": resolved.username,
                            "display_name": resolved.display_name,
                            "profile_image": resolved.profile_image,
                            "remote_url": resolved.remote_url,
                        })
    else:
        # Plain text: search local users and remote users by username
        with get_session() as s:
            local = s.query(User).filter(
                func.lower(User.username).contains(q.lower()),
                User.is_remote == False,
        ).limit(5).all()
            for u in local:
                results.append({
                    "source": "local",
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "profile_image": u.profile_image,
                    "remote_url": None,
                })
            # Also search remote users by username
            remote = s.query(User).filter(
                func.lower(User.username).contains(q.lower()),
                User.is_remote == True,
            ).limit(10).all()
            for u in remote:
                results.append({
                    "source": "remote_cached",
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "profile_image": u.profile_image,
                    "remote_url": u.remote_url,
                })
    return {"results": results}


@admin_router.post("/admin/remote-server/{domain:path}/block")
def api_admin_remote_server_block(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        existing = s.query(FederationBlock).filter_by(domain=domain).first()
        if not existing:
            s.add(FederationBlock(domain=domain, reason="", created_by_id=user.id))
            s.commit()
    log_admin_action(user.id, user.username, "federation_block", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.post("/admin/remote-server/{domain:path}/unblock")
def api_admin_remote_server_unblock(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        s.query(FederationBlock).filter_by(domain=domain).delete()
        s.commit()
    log_admin_action(user.id, user.username, "federation_unblock", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.post("/admin/remote-server/{domain:path}/mute")
def api_admin_remote_server_mute(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        mute = s.query(MutedServer).filter_by(domain=domain).first()
        if not mute:
            mute = MutedServer(domain=domain, muted=True, media_muted=False, created_by_id=user.id)
            s.add(mute)
        else:
            mute.muted = True
        # Apply limit action to all users from this domain
        for u in _domain_users(s, domain):
            u.is_limited = True
            u.is_sensitive = True
            for p in s.query(Post).filter(Post.author_id == u.id, Post.visibility == "public").all():
                p.original_visibility = p.visibility
                p.visibility = "home"
        s.commit()
    log_admin_action(user.id, user.username, "server_mute", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.post("/admin/remote-server/{domain:path}/unmute")
def api_admin_remote_server_unmute(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        mute = s.query(MutedServer).filter_by(domain=domain).first()
        if mute:
            mute.muted = False
            # Only delete the row if both flags are off
            if not mute.media_muted:
                s.delete(mute)
        # Restore visibility for users from this domain
        for u in _domain_users(s, domain):
            u.is_limited = False
            u.is_sensitive = False
            for p in s.query(Post).filter(Post.author_id == u.id, Post.original_visibility != "").all():
                p.visibility = p.original_visibility
                p.original_visibility = ""
        s.commit()
    log_admin_action(user.id, user.username, "server_unmute", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.post("/admin/remote-server/{domain:path}/media-mute")
def api_admin_remote_server_media_mute(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        mute = s.query(MutedServer).filter_by(domain=domain).first()
        if not mute:
            mute = MutedServer(domain=domain, muted=False, media_muted=True, created_by_id=user.id)
            s.add(mute)
        else:
            mute.media_muted = True
        for u in _domain_users(s, domain):
            u.is_sensitive = True
        s.commit()
    log_admin_action(user.id, user.username, "server_media_mute", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.post("/admin/remote-server/{domain:path}/unmedia-mute")
def api_admin_remote_server_unmedia_mute(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        mute = s.query(MutedServer).filter_by(domain=domain).first()
        if mute:
            mute.media_muted = False
            if not mute.muted:
                s.delete(mute)
        # Only clear is_sensitive if the user is not also muted (which sets is_sensitive)
        for u in _domain_users(s, domain):
            mute_user = s.query(MutedServer).filter_by(domain=domain).first()
            if not mute_user or not mute_user.muted:
                u.is_sensitive = False
        s.commit()
    log_admin_action(user.id, user.username, "server_unmedia_mute", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@admin_router.post("/admin/remote-server/{domain:path}/purge")
def api_admin_remote_server_purge(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    storage = get_storage()
    with get_session() as s:
        users = _domain_users(s, domain)
        user_ids = [u.id for u in users]
        # Delete stored avatar/header files first
        for u in users:
            if u.profile_image:
                storage.delete(u.profile_image)
            if u.header_image:
                storage.delete(u.header_image)
        if user_ids:
            # Delete follows involving these users
            s.query(Follow).filter(
                or_(Follow.follower_id.in_(user_ids), Follow.following_id.in_(user_ids))
            ).delete(synchronize_session=False)
            # Delete notifications
            s.query(Notification).filter(
                or_(Notification.from_user_id.in_(user_ids), Notification.user_id.in_(user_ids))
            ).delete(synchronize_session=False)
            # Delete likes, boosts, bookmarks
            s.query(Like).filter(Like.user_id.in_(user_ids)).delete(synchronize_session=False)
            s.query(Boost).filter(Boost.user_id.in_(user_ids)).delete(synchronize_session=False)
            s.query(Bookmark).filter(Bookmark.user_id.in_(user_ids)).delete(synchronize_session=False)
            s.query(Vote).filter(Vote.user_id.in_(user_ids)).delete(synchronize_session=False)
            # Convert mentions to the purged domain to plain text in local posts
            _esc = re.escape(domain)
            _mention_re = re.compile(
                r'<span class="h-card"[^>]*>'
                r'<a href="[^"]*' + _esc + r'[^"]*" class="u-url mention">'
                r'@<span>([^<]+)</span></a></span>'
            )
            _mention_re2 = re.compile(
                r'<a href="[^"]*' + _esc + r'[^"]*" class="mention">@([^<]+)</a>'
            )
            for _p in s.query(Post).filter(Post.author_id.notin_(user_ids), Post.content.contains(domain)).all():
                _new = _mention_re.sub(r'@\1@' + domain, _p.content)
                _new = _mention_re2.sub(r'@\1@' + domain, _new)
                if _new != _p.content:
                    _p.content = _new
            # Delete posts (FK: in_reply_to_id)
            for p in s.query(Post).filter(Post.author_id.in_(user_ids)).all():
                s.query(Post).filter(Post.in_reply_to_id == p.id).update({"in_reply_to_id": None})
                s.delete(p)
            # Finally delete the users
            s.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        # Delete AdminLog entries for this domain
        s.query(AdminLog).filter(
            AdminLog.target_type == "domain",
            AdminLog.target_username == domain,
        ).delete(synchronize_session=False)
        # Clean up federation blocks, mutes, muted_servers
        s.query(FederationBlock).filter_by(domain=domain).delete()
        s.query(MutedServer).filter_by(domain=domain).delete()
        s.commit()
    return {"ok": True}


@admin_router.post("/admin/federation-mode")
def api_admin_set_federation_mode(request: Request, mode: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if mode not in ("whitelist", "blacklist"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    with get_session() as s:
        settings = ServerSetting.get(s)
        old_mode = settings.federation_mode
        settings.federation_mode = mode
        s.commit()
    log_admin_action(user.id, user.username, "federation_mode", details=f"{old_mode} -> {mode}", ip_address=request.client.host if request.client else "")
    return {"ok": True, "mode": mode}


@admin_router.get("/admin/federation-mode")
def api_admin_get_federation_mode(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        settings = ServerSetting.get(s)
        return {"mode": settings.federation_mode or "blacklist"}


@admin_router.get("/admin/settings")
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
            "enable_reactions": bool(settings.enable_reactions),
        }


@admin_router.post("/admin/settings")
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
        if logo and settings.logo and logo != settings.logo:
            storage.delete(settings.logo)
        elif not logo and settings.logo:
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


@admin_router.get("/admin/logs")
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


__all__ = ["admin_router"]
