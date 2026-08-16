"""Account settings, password/email, media upload endpoints extracted from _settings.py."""
import io
import json
import re
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps
from sqlalchemy import or_

from app.utils.image import guard_image

guard_image()

from app.config.settings import BASE_URL
from app.core.activitypub import _post_to_inbox
from app.core.auth import delete_user_sessions, hash_password, require_active_auth, require_auth, verify_password
from app.core.permissions import has_permission
from app.core.threads import spawn
from app.core.timeline_stream import broadcast_refresh_notifs
from app.db.database import get_session
from app.models import (
    BlockedDomain,
    Bookmark,
    Boost,
    Episode,
    EpisodeView,
    Follow,
    Like,
    Notification,
    Novel,
    Post,
    PushSubscription,
    SeriesFollow,
    SeriesMute,
    SeriesNotice,
    User,
    Vote,
)
from app.routes.api._auth import _send_verification_email
from app.utils.log import log_admin_action
from app.utils.storage import get_storage
from app.utils.upload import MAX_IMAGE_SIZE, _validate_upload

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
        if has_permission(user, "content.manage"):
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
    require_active_auth(request)
    storage = get_storage()
    ext, is_image, _is_video, _ = _validate_upload(file, allow_video=True, max_size=MAX_IMAGE_SIZE, label="미디어")
    name = f"{uuid4().hex}.webp" if is_image else f"{uuid4().hex}{ext}"
    key = f"media/{name}"
    if is_image:
        try:
            img: Image.Image = Image.open(io.BytesIO(file.file.read()))
        except (Image.DecompressionBombError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail="미디어 이미지 해상도가 너무 큽니다.") from exc
        img = ImageOps.exif_transpose(img) or img
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
    from app.core.auth import delete_user_sessions
    delete_user_sessions(user.id)
    log_admin_action(user.id, user.username, "change_password", ip_address=request.client.host if request.client else "")
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
            if local and (local.id == user.id or getattr(local, 'is_suspended', False) or getattr(local, 'is_deactivated', False)):
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
    if user.role in ("admin", "owner"):
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
            for like in s.query(Like.user_id).filter(Like.post_id.in_(_my_post_ids)).all():
                _interacted.add(like.user_id)
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
                spawn(_post_to_inbox, _inbox, _delete_activity, db)

        _del_notif_user_ids = set()
        _posts = s.query(Post).filter_by(author_id=db.id).all()
        _post_ids = [p.id for p in _posts]
        _has_replies = set()
        if _post_ids:
            for (_rid,) in s.query(Post.in_reply_to_id).filter(Post.in_reply_to_id.in_(_post_ids)).all():
                if _rid:
                    _has_replies.add(_rid)
            _ap_to_pid = {p.ap_id: p.id for p in _posts if p.ap_id}
            if _ap_to_pid:
                for (_rid,) in s.query(Post.in_reply_to_ap_id).filter(
                    Post.in_reply_to_ap_id.in_(list(_ap_to_pid))
                ).all():
                    if _rid in _ap_to_pid:
                        _has_replies.add(_ap_to_pid[_rid])
            s.query(Like).filter(Like.post_id.in_(_post_ids)).delete(synchronize_session=False)
            s.query(Boost).filter(Boost.post_id.in_(_post_ids)).delete(synchronize_session=False)
            s.query(Bookmark).filter(Bookmark.post_id.in_(_post_ids)).delete(synchronize_session=False)
            s.query(Vote).filter(Vote.post_id.in_(_post_ids)).delete(synchronize_session=False)
            for (_n,) in s.query(Notification.user_id).filter(Notification.post_id.in_(_post_ids)).distinct().all():
                _del_notif_user_ids.add(_n)
            s.query(Notification).filter(Notification.post_id.in_(_post_ids)).delete(synchronize_session=False)
        for p in _posts:
            if p.id in _has_replies:
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
                        spawn(_post_to_inbox, _inbox, _delete_note, db)
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
    delete_user_sessions(user_id)

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
