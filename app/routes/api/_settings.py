"""Settings, account migration, import/export, and media upload endpoints extracted from _core.py."""
import os
import re
import csv
import json
import io
import secrets
import logging
import threading
import zipfile
from uuid import uuid4
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from PIL import Image, ImageOps
from sqlalchemy import desc, or_, and_, func
from sqlalchemy.orm import selectinload

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, EpisodeDraft, SeriesFollow, SeriesNotice, Tag, CustomEmoji, ProfileNote, Report, ServerRule, BlockedDomain, FederationBlock, AllowedServer, MutedServer, ServerSetting, AdminLog, UserMute, UserBlock, SeriesMute, KeywordMute, EpisodeView, PushSubscription, LoginSession
from app.serializers import _user_json
from app.config.settings import BASE_URL, SECRET_KEY
from app.core.activitypub import _post_to_inbox
from app.core.timeline_stream import broadcast_refresh_notifs
from app.db.database import get_session
from app.routes.auth import require_auth, require_active_auth, hash_password, verify_password
from app.utils.datetime import _fmt_dt
from app.utils.log import log_admin_action
from app.utils.storage import get_storage

from app.routes.api._core import _validate_upload, MAX_IMAGE_SIZE, MAX_VIDEO_SIZE
from app.routes.api._auth import _send_verification_email

logger = logging.getLogger("writ.api.settings")

settings_router = APIRouter()


@settings_router.post("/settings/update")
def api_update_settings(request: Request, default_visibility: str = Form("public"),
                        episode_default_visibility: str = Form("public"),
                        is_locked: bool = Form(False),
                        show_badge: bool = Form(False),
                        is_bot: bool = Form(False),
                        follow_list_visibility: str = Form("public"),
                        enable_reactions: bool = Form(True),
                        post_lifetime: int = Form(0),
                        post_lifetime_exceptions: str = Form("[]")):
    user = require_auth(request)
    valid_post = ("public", "home", "followers", "mention")
    if default_visibility not in valid_post:
        default_visibility = "public"
    if episode_default_visibility not in valid_post:
        episode_default_visibility = "public"
    if follow_list_visibility not in ("public", "private"):
        follow_list_visibility = "public"
    valid_lifetimes = [0, 7, 14, 30, 60, 90, 180, 365, 730]
    if post_lifetime not in valid_lifetimes:
        post_lifetime = 0
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        db.default_visibility = default_visibility
        db.episode_default_visibility = episode_default_visibility
        db.is_locked = is_locked
        db.is_bot = is_bot
        db.follow_list_visibility = follow_list_visibility
        db.enable_reactions = enable_reactions
        db.post_lifetime = post_lifetime
        try:
            exc = json.loads(post_lifetime_exceptions)
            if isinstance(exc, list):
                db.post_lifetime_exceptions = exc
        except Exception:
            pass
        if user.role in ("admin", "moderator", "owner"):
            db.show_badge = show_badge
        s.commit()
    return {"ok": True}


@settings_router.post("/settings/change-email")
def api_settings_change_email(request: Request, email: str = Form(...)):
    user = require_auth(request)
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    domain = email.split("@")[-1] if "@" in email else ""
    with get_session() as s:
        if domain:
            blocked = s.query(BlockedDomain).filter_by(domain=domain).first()
            if blocked:
                raise HTTPException(status_code=400, detail="해당 이메일 도메인은 가입이 차단되었습니다.")
        existing = s.query(User).filter(User.email == email, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        db = s.query(User).filter_by(id=user.id).first()
        old_email = db.email
        db.email = email
        db.email_verified = False
        db.verification_token = ""
        _send_verification_email(db)
        s.commit()
    log_admin_action(user.id, user.username, "change_email", details=f"{old_email} -> {email}", ip_address=request.client.host if request.client else "")
    return {"ok": True, "email_changed": True}


@settings_router.post("/settings/send-verification-email")
def api_settings_send_verification(request: Request):
    user = require_auth(request)
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        if db.email_verified:
            return {"ok": True, "already_verified": True}
        _send_verification_email(db)
        s.commit()
    return {"ok": True, "email_sent": True}


@settings_router.post("/media/upload")
def api_upload_media(request: Request, file: UploadFile = File(...)):
    user = require_active_auth(request)
    storage = get_storage()
    ext, is_image, is_video, _ = _validate_upload(file, allow_video=True, max_size=MAX_IMAGE_SIZE, label="미디어")
    name = f"{uuid4().hex}.webp" if is_image else f"{uuid4().hex}{ext}"
    key = f"media/{name}"
    if is_image:
        img = Image.open(io.BytesIO(file.file.read()))
        img = ImageOps.exif_transpose(img)
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=85, lossless=(img.mode == "RGBA"))
        storage.save(key, buf.getvalue())
        url = storage.url(key)
    else:
        storage.save(key, file.file.read())
        url = storage.url(key)
    return {"url": url, "type": "image" if is_image else "video"}


@settings_router.post("/settings/change-password")
def api_settings_change_password(request: Request, current_password: str = Form(...), new_password: str = Form(...)):
    user = require_auth(request)
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        stored = db.password_hash
        if ":" not in stored:
            raise HTTPException(status_code=400, detail="Invalid credentials")
        salt, hval = stored.split(":", 1)
        if not verify_password(current_password, salt, hval):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if verify_password(new_password, salt, hval):
            raise HTTPException(status_code=400, detail="New password must be different from current password")
        new_salt, new_hsh = hash_password(new_password)
        db.password_hash = new_salt + ":" + new_hsh
        s.commit()
    log_admin_action(user.id, user.username, "change_password", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@settings_router.post("/settings/migrate")
def api_migrate_account(request: Request, target_username: str = Form(...), series_ids: str = Form("[]")):
    user = require_auth(request)
    if user.is_frozen:
        raise HTTPException(status_code=400, detail="이미 동결된 계정입니다.")
    with get_session() as s:
        target = s.query(User).filter_by(username=target_username.strip(), is_remote=False).first()
        if not target:
            raise HTTPException(status_code=404, detail="대상 계정을 찾을 수 없습니다.")
        if target.id == user.id:
            raise HTTPException(status_code=400, detail="자기 자신에게 이전할 수 없습니다.")
        if target.is_frozen:
            raise HTTPException(status_code=400, detail="대상 계정이 동결되어 있습니다.")
        if getattr(target, 'is_deactivated', False) or getattr(target, 'moved_to', ''):
            raise HTTPException(status_code=400, detail="대상 계정이 이미 이전된 계정입니다.")

        try:
            sids = json.loads(series_ids)
            if not isinstance(sids, list):
                sids = []
        except (json.JSONDecodeError, TypeError):
            sids = []

        meta = json.dumps({
            "type": "migrate_request",
            "from_user_id": user.id,
            "from_username": user.username,
            "from_display": user.display_name or user.username,
            "series_ids": sids,
        })
        s.add(Notification(
            user_id=target.id, from_user_id=user.id,
            notification_type="moderation",
            metadata_json=meta,
        ))
        s.commit()

    return {"ok": True, "message": f"{target_username}님에게 이전 요청을 보냈습니다. 상대방이 수락하면 이전이 완료됩니다."}


@settings_router.post("/settings/migrate/approve")
def api_approve_migrate(request: Request, notification_id: int = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        n = s.query(Notification).filter_by(id=notification_id, user_id=user.id).first()
        if not n or n.notification_type != "moderation":
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")
        meta = {}
        try:
            meta = json.loads(n.metadata_json or "{}")
        except json.JSONDecodeError:
            pass
        if meta.get("type") != "migrate_request":
            raise HTTPException(status_code=400, detail="잘못된 요청입니다.")

        from_user_id = meta.get("from_user_id")
        from_user = s.query(User).get(from_user_id)
        if not from_user:
            raise HTTPException(status_code=404, detail="요청한 계정을 찾을 수 없습니다.")
        if getattr(from_user, 'is_deactivated', False):
            raise HTTPException(status_code=400, detail="이미 이전된 계정입니다.")

        series_ids = meta.get("series_ids", [])
        if series_ids:
            novels = s.query(Novel).filter(Novel.id.in_(series_ids), Novel.author_id == from_user_id).all()
            for nv in novels:
                nv.author_id = user.id

        if from_user:
            from_user.is_deactivated = True
            from_user.is_frozen = False
            from_user.is_suspended = False
            from_user.session_token = ""
            from_user.moved_to = f"{BASE_URL}/@{user.username}"
            from_user.aliases = []

        s.delete(n)
        s.commit()

        log_admin_action(user.id, user.username, "account_migrated", target_type="user", target_id=from_user.id if from_user else 0, target_username=from_user.username if from_user else "", ip_address=request.client.host if request.client else "")

    return {"ok": True, "message": "계정 이전이 완료되었습니다."}


@settings_router.post("/settings/migrate/reject")
def api_reject_migrate(request: Request, notification_id: int = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        n = s.query(Notification).filter_by(id=notification_id, user_id=user.id).first()
        if n:
            s.delete(n)
            s.commit()
    return {"ok": True}


@settings_router.post("/settings/aliases")
def api_set_aliases(request: Request, aliases: str = Form("[]")):
    user = require_auth(request)
    try:
        parsed = json.loads(aliases)
        if not isinstance(parsed, list):
            parsed = []
    except (json.JSONDecodeError, TypeError):
        parsed = []
    parsed = [a.strip() for a in parsed if isinstance(a, str) and a.strip()]
    own_handle = f"{user.username}@{_domain_from_actor(user)}"
    own_handle2 = user.username
    parsed = [a for a in parsed if a not in (own_handle, own_handle2)]
    with get_session() as s:
        for alias in parsed[:]:
            uname = alias.split("@")[0] if "@" in alias else alias
            local = s.query(User).filter_by(username=uname, is_remote=False).first()
            if local:
                if local.id == user.id:
                    parsed.remove(alias)
                elif getattr(local, 'is_suspended', False) or getattr(local, 'is_deactivated', False):
                    parsed.remove(alias)
        db = s.query(User).filter_by(id=user.id).first()
        db.aliases = parsed
        s.commit()
    return {"ok": True, "aliases": parsed}


@settings_router.get("/settings/aliases")
def api_get_aliases(request: Request):
    user = require_auth(request)
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        return {"aliases": (db.aliases or []) if hasattr(db, 'aliases') else []}


@settings_router.post("/settings/reactivate")
def api_reactivate_account(request: Request):
    user = require_auth(request)
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        if not getattr(db, 'is_deactivated', False):
            raise HTTPException(status_code=400, detail="비활성화된 계정이 아닙니다.")
        db.is_deactivated = False
        db.moved_to = ""
        db.session_token = ""
        s.commit()
    return {"ok": True}


@settings_router.post("/settings/delete-account")
def api_delete_account(request: Request, password: str = Form(...), confirm: str = Form(...)):
    user = require_auth(request)
    if user.is_admin:
        raise HTTPException(status_code=400, detail="관리자 계정은 탈퇴할 수 없습니다.")
    if confirm != user.username:
        raise HTTPException(status_code=400, detail=f"확인을 위해 '{user.username}'을(를) 입력하세요.")
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        stored = db.password_hash
        if ":" not in stored:
            raise HTTPException(status_code=400, detail="비밀번호 확인 실패")
        salt, hval = stored.split(":", 1)
        if not verify_password(password, salt, hval):
            raise HTTPException(status_code=400, detail="비밀번호가 올바르지 않습니다.")

        _actor_uri = db.actor_uri()
        _interacted = set()
        for f in s.query(Follow).filter_by(following_id=db.id, accepted=True).all():
            _interacted.add(f.follower_id)
        for f in s.query(Follow).filter_by(follower_id=db.id, accepted=True).all():
            _interacted.add(f.following_id)
        _my_post_ids = [p.id for p in s.query(Post.id).filter_by(author_id=db.id).all()]
        if _my_post_ids:
            for b in s.query(Boost.user_id).filter(Boost.post_id.in_(_my_post_ids)).all():
                _interacted.add(b.user_id)
            for l in s.query(Like.user_id).filter(Like.post_id.in_(_my_post_ids)).all():
                _interacted.add(l.user_id)
            for r in s.query(Post.author_id).filter(Post.in_reply_to_id.in_(_my_post_ids)).all():
                _interacted.add(r.author_id)
        _inboxes = {}
        for _uid in _interacted:
            _u = s.query(User).get(_uid)
            if not _u or not _u.is_remote:
                continue
            _key = _u.shared_inbox_url or _u.inbox_url
            if _key:
                _inboxes[_key] = True
        if _inboxes:
            _delete_activity = {
                "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
                "id": f"{_actor_uri}#delete",
                "type": "Delete",
                "actor": _actor_uri,
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "object": _actor_uri,
            }
            for _inbox in _inboxes:
                threading.Thread(target=_post_to_inbox, args=(_inbox, _delete_activity, db), daemon=True).start()

        _del_notif_user_ids = set()
        for p in s.query(Post).filter_by(author_id=db.id).all():
            has_replies = s.query(Post).filter(Post.in_reply_to_id == p.id).first() is not None
            if not has_replies and p.ap_id:
                has_replies = s.query(Post).filter(Post.in_reply_to_ap_id == p.ap_id).first() is not None
            s.query(Like).filter(Like.post_id == p.id).delete()
            s.query(Boost).filter(Boost.post_id == p.id).delete()
            s.query(Bookmark).filter(Bookmark.post_id == p.id).delete()
            s.query(Vote).filter(Vote.post_id == p.id).delete()
            for _n in s.query(Notification.user_id).filter(Notification.post_id == p.id).distinct().all():
                _del_notif_user_ids.add(_n[0])
            s.query(Notification).filter(Notification.post_id == p.id).delete()
            if has_replies:
                p.content = ""
                p.media_attachments = []
                p.poll_data = None
                p.link_preview = None
                p.is_deleted = True
                if p.ap_id and p.ap_id.startswith("http"):
                    _delete_note = {
                        "@context": "https://www.w3.org/ns/activitystreams",
                        "id": f"{p.ap_id}#delete",
                        "type": "Delete",
                        "actor": _actor_uri,
                        "to": ["https://www.w3.org/ns/activitystreams#Public"],
                        "object": {"id": p.ap_id, "type": "Note"},
                    }
                    for _inbox in _inboxes:
                        threading.Thread(target=_post_to_inbox, args=(_inbox, _delete_note, db), daemon=True).start()
            else:
                s.delete(p)

        for n in s.query(Novel).filter_by(author_id=db.id).all():
            for e in s.query(Episode).filter_by(novel_id=n.id).all():
                s.query(EpisodeView).filter(EpisodeView.episode_id == e.id).delete()
                s.delete(e)
            s.query(SeriesFollow).filter(SeriesFollow.novel_id == n.id).delete()
            s.query(SeriesNotice).filter(SeriesNotice.novel_id == n.id).delete()
            s.query(SeriesMute).filter(SeriesMute.novel_id == n.id).delete()
            s.delete(n)

        s.query(Follow).filter(
            or_(Follow.follower_id == db.id, Follow.following_id == db.id)
        ).delete()

        s.query(Notification).filter(
            or_(Notification.user_id == db.id, Notification.from_user_id == db.id)
        ).delete()
        s.query(PushSubscription).filter_by(user_id=db.id).delete()

        db.display_name = "탈퇴한 회원"
        db.summary = ""
        db.email = f"deleted_{db.id}@deleted.local"
        db.email_verified = False
        db.profile_image = ""
        db.header_image = ""
        db.password_hash = "deleted"
        db.is_deactivated = True
        db.is_locked = False
        db.is_bot = False
        db.custom_fields = []
        db.profile_hashtags = []
        s.commit()
        try:
            for _uid in _del_notif_user_ids:
                if _uid != db.id:
                    broadcast_refresh_notifs(_uid)
        except Exception:
            pass
        user_id = db.id
        username = db.username

    log_admin_action(user_id, username, "delete_account_self", ip_address=request.client.host if request.client else "")

    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    resp.delete_cookie("csrf_token")
    return resp


def _domain_from_actor(u) -> str:
    if not u:
        return ""
    if u.is_remote and u.remote_url:
        return urlparse(u.remote_url).hostname or ""
    return urlparse(BASE_URL).hostname or ""


@settings_router.get("/settings/export/{export_type}")
def api_export_account(request: Request, export_type: str):
    user = require_auth(request)
    buf = io.StringIO()
    w = csv.writer(buf)
    with get_session() as s:
        if export_type == "follows":
            w.writerow(["Account address", "Show boosts", "Notify on new posts"])
            follows = s.query(Follow).filter_by(follower_id=user.id, accepted=True).all()
            for f in follows:
                target = s.query(User).get(f.following_id)
                if target:
                    handle = target.username
                    w.writerow([handle, "true", "false"])
        elif export_type == "mutes":
            w.writerow(["Account address"])
            mutes = s.query(UserMute).filter_by(user_id=user.id).all()
            for m in mutes:
                target = s.query(User).get(m.target_user_id)
                if target:
                    handle = target.username
                    w.writerow([handle])
        elif export_type == "blocks":
            w.writerow(["Account address"])
            blocks = s.query(UserBlock).filter_by(user_id=user.id).all()
            for b in blocks:
                target = s.query(User).get(b.target_user_id)
                if target:
                    handle = target.username
                    w.writerow([handle])
        elif export_type == "bookmarks":
            w.writerow(["Post URL", "Created at"])
            bookmarks = s.query(Bookmark).filter_by(user_id=user.id).all()
            for bm in bookmarks:
                post = s.query(Post).get(bm.post_id)
                if post:
                    w.writerow([post.ap_id or f"{BASE_URL}/post/{post.id}", str(bm.created_at)])
        elif export_type == "keyword_mutes":
            w.writerow(["Keyword", "Whole word"])
            kw_mutes = s.query(KeywordMute).filter_by(user_id=user.id).all()
            for kw in kw_mutes:
                w.writerow([kw.keyword, "false"])
        elif export_type == "domain_blocks":
            w.writerow(["Domain"])
            blocks = s.query(UserBlock).filter_by(user_id=user.id).all()
            domains = set()
            for b in blocks:
                target = s.query(User).get(b.target_user_id)
                if target and target.is_remote:
                    domain = _domain_from_actor(target)
                    if domain:
                        domains.add(domain)
            for d in sorted(domains):
                w.writerow([d])
        elif export_type == "posts":
            w.writerow(["id", "content", "created_at"])
            posts = s.query(Post).filter_by(author_id=user.id, is_deleted=False).all()
            for p in posts:
                w.writerow([p.id, p.content or "", str(p.created_at)])
        else:
            raise HTTPException(status_code=400, detail="Invalid type")
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={export_type}.csv"})


@settings_router.get("/settings/export-data")
def api_export_data(request: Request):
    user = require_auth(request)
    with get_session() as s:
        follows = []
        for f in s.query(Follow).filter_by(follower_id=user.id, accepted=True).all():
            target = s.query(User).get(f.following_id)
            if target:
                follows.append({"handle": target.username, "display_name": target.display_name, "notify_on_post": f.notify_on_post})
        mutes = []
        for m in s.query(UserMute).filter_by(user_id=user.id).all():
            target = s.query(User).get(m.target_user_id)
            if target:
                mutes.append({"handle": target.username, "display_name": target.display_name})
        blocks = []
        for b in s.query(UserBlock).filter_by(user_id=user.id).all():
            target = s.query(User).get(b.target_user_id)
            if target:
                blocks.append({"handle": target.username, "display_name": target.display_name})
        bookmarks = []
        for bm in s.query(Bookmark).filter_by(user_id=user.id).all():
            post = s.query(Post).get(bm.post_id)
            if post and not post.is_deleted:
                bookmarks.append({"url": post.ap_id or f"{BASE_URL}/post/{post.id}", "created_at": str(bm.created_at)})
        keyword_mutes = []
        for kw in s.query(KeywordMute).filter_by(user_id=user.id).all():
            keyword_mutes.append({"keyword": kw.keyword, "name": kw.name or "", "mode": kw.mode, "is_regex": kw.is_regex})
        return {"follows": follows, "mutes": mutes, "blocks": blocks, "bookmarks": bookmarks, "keyword_mutes": keyword_mutes}


@settings_router.get("/settings/export-archive")
def api_export_archive(request: Request):
    user = require_auth(request)
    buf = io.BytesIO()
    with get_session() as s:
        posts = s.query(Post).filter_by(author_id=user.id, is_deleted=False).order_by(Post.created_at).all()
        posts_data = []
        for p in posts:
            posts_data.append({
                "id": p.id, "content": p.content or "", "summary": p.summary or "",
                "visibility": p.visibility, "created_at": str(p.created_at),
                "media_attachments": p.media_attachments or [],
                "poll_data": p.poll_data, "is_sensitive": p.is_sensitive,
            })
        novels = s.query(Novel).filter_by(author_id=user.id).order_by(Novel.created_at).all()
        novels_data = []
        for n in novels:
            eps = s.query(Episode).filter_by(novel_id=n.id).order_by(Episode.episode_number).all()
            episodes_data = []
            for e in eps:
                episodes_data.append({
                    "episode_number": e.episode_number, "title": e.title,
                    "content": e.content, "summary": e.summary or "",
                    "is_published": e.is_published, "created_at": str(e.created_at),
                })
            novels_data.append({
                "title": n.title, "description": n.description or "", "tags": n.tags or "",
                "status": n.status, "visibility": n.visibility,
                "is_sensitive": n.is_sensitive, "created_at": str(n.created_at),
                "episodes": episodes_data,
            })
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("posts.json", json.dumps(posts_data, ensure_ascii=False, indent=2))
        zf.writestr("novels.json", json.dumps(novels_data, ensure_ascii=False, indent=2))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename=writ_archive_{user.username}.zip"})


@settings_router.post("/settings/import-data")
def api_import_data(request: Request, data: str = Form(...)):
    user = require_active_auth(request)
    try:
        payload = json.loads(data)
    except Exception:
        raise HTTPException(status_code=400, detail="잘못된 JSON 형식입니다.")
    imported = {"follows": 0, "mutes": 0, "blocks": 0, "bookmarks": 0, "keyword_mutes": 0}
    with get_session() as s:
        for item in payload.get("follows", []):
            handle = item.get("handle", "").strip().lower()
            if not handle:
                continue
            target = s.query(User).filter_by(username=handle, is_remote=False).first()
            if not target or target.id == user.id:
                continue
            exists = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
            if not exists:
                s.add(Follow(follower_id=user.id, following_id=target.id, accepted=True))
                imported["follows"] += 1
        for item in payload.get("mutes", []):
            handle = item.get("handle", "").strip().lower()
            if not handle:
                continue
            target = s.query(User).filter_by(username=handle, is_remote=False).first()
            if not target or target.id == user.id:
                continue
            exists = s.query(UserMute).filter_by(user_id=user.id, target_user_id=target.id).first()
            if not exists:
                s.add(UserMute(user_id=user.id, target_user_id=target.id))
                imported["mutes"] += 1
        for item in payload.get("blocks", []):
            handle = item.get("handle", "").strip().lower()
            if not handle:
                continue
            target = s.query(User).filter_by(username=handle, is_remote=False).first()
            if not target or target.id == user.id:
                continue
            exists = s.query(UserBlock).filter_by(user_id=user.id, target_user_id=target.id).first()
            if not exists:
                s.add(UserBlock(user_id=user.id, target_user_id=target.id))
                imported["blocks"] += 1
        for item in payload.get("bookmarks", []):
            url = item.get("url", "")
            if not url:
                continue
            post = s.query(Post).filter(Post.ap_id == url).first()
            if not post:
                m = re.search(r"/post/(\d+)", url)
                if m:
                    post = s.query(Post).filter_by(id=int(m.group(1))).first()
            if not post or post.is_deleted:
                continue
            exists = s.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first()
            if not exists:
                s.add(Bookmark(user_id=user.id, post_id=post.id))
                imported["bookmarks"] += 1
        for item in payload.get("keyword_mutes", []):
            keyword = item.get("keyword", "").strip()
            if not keyword:
                continue
            exists = s.query(KeywordMute).filter_by(user_id=user.id, keyword=keyword).first()
            if not exists:
                s.add(KeywordMute(user_id=user.id, keyword=keyword, name=item.get("name", ""), mode=item.get("mode", "or"), is_regex=item.get("is_regex", False)))
                imported["keyword_mutes"] += 1
        s.commit()
    return {"ok": True, "imported": imported}


@settings_router.post("/settings/archive-request")
def api_archive_request(request: Request):
    user = require_auth(request)
    with get_session() as s:
        admins = s.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
        for admin in admins:
            if admin.id == user.id:
                continue
            s.add(Notification(
                user_id=admin.id, from_user_id=user.id,
                notification_type="moderation",
                metadata_json=json.dumps({"type": "archive_request", "user_id": user.id, "username": user.username}),
            ))
        s.commit()
    return {"ok": True, "message": "아카이브 요청이 접수되었습니다."}
