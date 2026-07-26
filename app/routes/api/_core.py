"""Core API endpoints — admin extracted to _admin.py."""
import os
import base64
import csv
import re
import json
import io
import asyncio
from datetime import datetime, timedelta, timezone
import uuid
import logging
import secrets
import time
import httpx
import threading
import traceback
from uuid import uuid4
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key, Encoding, PublicFormat
from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse, Response, FileResponse
from PIL import Image
from sqlalchemy import desc, or_, and_, func, String, text, select
from sqlalchemy.orm import selectinload, Session, joinedload
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from urllib.parse import urlparse

from email.mime.text import MIMEText
import smtplib

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, EpisodeDraft, SeriesFollow, SeriesNotice, Tag, CustomEmoji, ProfileNote, Report, ServerRule, BlockedDomain, FederationBlock, AllowedServer, MutedServer, ServerSetting, AdminLog, UserMute, UserBlock, SeriesMute, KeywordMute, EpisodeView, PushSubscription, LoginSession, ServerSetting
from app.utils.to_ap_serializer import to_ap_note, to_ap_create, to_ap_actor
from app.serializers import _post_json, _user_json
from app.config.settings import BASE_URL, MAX_POST_LENGTH, SECRET_KEY, S3_ENABLED, APP_ENV, SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, INITIAL_OWNER_PASSWORD, SESSION_EXPIRE_DAYS
from app.core.activitypub import _fetch_remote_post, broadcast_to_followers, _post_to_inbox, _federation_allowed, _build_reactions, _resolve_actor, _send_delete_post, _send_flag, _send_accept, _send_reject, _get_instance_actor, _validate_url, _fetch_remote_count
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user, VAPID_PUBLIC_KEY
from app.core.timeline_stream import broadcast_post, add_stream, remove_stream, broadcast_refresh_notifs, add_notif_stream, remove_notif_stream, broadcast_reaction_update, add_post_stream, remove_post_stream, broadcast_notif_sound, broadcast_delete
from app.db.database import get_session, get_db
from app.db.mention_resolver import resolve_handles_to_ids
from app.routes.auth import require_auth, require_active_auth, get_current_user, hash_password, verify_password, create_session, get_session_key_from_cookie, delete_session_by_key
from app.utils.content_parser import process_post_content, extract_mentions
from app.utils.crypto import encrypt_key, get_private_key, generate_keypair, sign_string, generate_csrf_token
from app.utils.datetime import _fmt_dt
from app.utils.emoji import EMOJI_DIR, _refresh_emoji_cache_forcibly, _emoji_url, _load_emojis
from app.utils.filter import _timeline_filter
from app.utils.log import log_admin_action
from app.utils.post import _get_descendant_ids
from app.utils.storage import LocalStorage, get_storage

# Auth rate limiting (IP-based, in-memory)
_auth_failures: dict[str, list[float]] = {}
_auth_lock = threading.Lock()
_AUTH_FAIL_WINDOW = 900  # 15 min
_AUTH_FAIL_MAX = 5
_AUTH_FAIL_BACKOFF_BASE = 60  # 1 min base

def _check_auth_rate_limit(ip: str) -> bool:
    now = time.time()
    with _auth_lock:
        timestamps = [t for t in _auth_failures.get(ip, []) if t > now - _AUTH_FAIL_WINDOW]
        _auth_failures[ip] = timestamps
        if len(timestamps) >= _AUTH_FAIL_MAX:
            return False
        timestamps.append(now)
        return True

def _record_auth_failure(ip: str):
    now = time.time()
    with _auth_lock:
        _auth_failures.setdefault(ip, []).append(now)

def _get_auth_backoff_seconds(ip: str) -> int:
    with _auth_lock:
        count = len([t for t in _auth_failures.get(ip, []) if t > time.time() - _AUTH_FAIL_WINDOW])
    if count < _AUTH_FAIL_MAX:
        return 0
    return _AUTH_FAIL_BACKOFF_BASE * (2 ** min(count - _AUTH_FAIL_MAX, 6))


logger = logging.getLogger("writ.api")

RESERVED_HANDLES = frozenset({
    "admin", "administrator", "root", "system", "moderator", "support",
    "nodeinfo", "well-known", "api", "auth", "oauth", "inbox", "outbox",
    "actor", "users", "accounts", "instance_actor", "login", "register", "writ",
})

router = APIRouter(prefix="/api")


ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogg", ".mov"}
ALLOWED_UPLOAD_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_AVATAR_SIZE = 5 * 1024 * 1024
IMAGE_MIME_PREFIXES = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/ico")
VIDEO_MIME_TYPES = {"video/mp4", "video/webm", "video/ogg", "video/quicktime"}


def _validate_upload(file: UploadFile, *, allow_video: bool = True, max_size: int = MAX_IMAGE_SIZE, label: str = "file"):
    ext = os.path.splitext(file.filename or "file")[1].lower() if file.filename else ""
    is_video = ext in ALLOWED_VIDEO_EXTENSIONS
    is_image = ext in ALLOWED_IMAGE_EXTENSIONS
    if not is_image and not (is_video and allow_video):
        raise HTTPException(status_code=400, detail=f"{label}: 지원하지 않는 파일 형식입니다")
    ct = (file.content_type or "").lower()
    if is_image and not any(ct.startswith(p) for p in IMAGE_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail=f"{label}: 이미지 MIME 타입이 올바르지 않습니다")
    if is_video and ct not in VIDEO_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"{label}: 비디오 MIME 타입이 올바르지 않습니다")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if is_video and size > MAX_VIDEO_SIZE:
        raise HTTPException(status_code=400, detail=f"{label}: 비디오 파일이 너무 큽니다 (최대 25MB)")
    if is_image and size > max_size:
        raise HTTPException(status_code=400, detail=f"{label}: 이미지 파일이 너무 큽니다 (최대 {max_size // (1024*1024)}MB)")
    return ext, is_image, is_video


def _can_view(post, viewer, session):
    if post.is_deleted:
        return False
    if viewer and post.author_id == viewer.id:
        return True
    v = post.visibility or "public"
    if v in ("public", "home"):
        return True
    if not viewer:
        return False
    if v == "followers":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return session.query(Follow).filter_by(
            follower_id=viewer.id, following_id=post.author_id, accepted=True
        ).first() is not None
    if v == "mention":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return False
    return True


def _json_array_has_user(column, user_id):
    """JSON 배열 컬럼에 user_id가 정확히 포함되어 있는지 확인"""
    if isinstance(column.type, postgresql.JSONB):
        return column.cast(JSONB).op('@>')(func.json_build_array(user_id).cast(JSONB))
    else:
        # SQLite fallback: cast to text and check containment via LIKE
        return column.cast(String).like(f'%{user_id}%')


TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


# ── Auth API ──

@router.get("/auth/me")
def api_me(request: Request, s: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    result = _user_json(user)
    _settings = ServerSetting.get(s)
    if not _settings.enable_reactions:
        result["enable_reactions"] = False
    resp = JSONResponse(result)
    secure = APP_ENV != "development"
    resp.set_cookie(key="csrf_token", value=generate_csrf_token(user.id), max_age=30*86400, httponly=False, samesite="lax", path="/", secure=secure)
    return resp


@router.post("/auth/login")
def api_login(request: Request, username: str = Form(...), password: str = Form(...)):
    try:
        client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0].strip()
        backoff = _get_auth_backoff_seconds(client_ip)
        if backoff > 0:
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
        if not _check_auth_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
        with get_session() as s:
            q = s.query(User).filter(User.is_remote == False)
            if "@" in username and "." in username:
                db_user = q.filter(User.email == username).first()
            else:
                db_user = q.filter(User.username == username).first()
            if not db_user:
                log_admin_action(None, username, "login_failed", details="user_not_found", ip_address=client_ip)
                _record_auth_failure(client_ip)
                raise HTTPException(status_code=401, detail="Invalid credentials")
            if getattr(db_user, 'is_frozen', False):
                log_admin_action(db_user.id, db_user.username, "login_blocked", details="frozen", ip_address=client_ip)
                raise HTTPException(status_code=403, detail="계정이 동결되었습니다.")
            if getattr(db_user, 'is_suspended', False):
                log_admin_action(db_user.id, db_user.username, "login_blocked", details="suspended", ip_address=client_ip)
                raise HTTPException(status_code=403, detail="계정이 정지되었습니다.")
            stored = db_user.password_hash
            if ":" not in stored:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            salt, hval = stored.split(":", 1)
            if not verify_password(password, salt, hval):
                log_admin_action(db_user.id, db_user.username, "login_failed", details="wrong_password", ip_address=client_ip)
                _record_auth_failure(client_ip)
                raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
            if not db_user.email_verified:
                log_admin_action(db_user.id, db_user.username, "login_blocked", details="email_not_verified", ip_address=client_ip)
                raise HTTPException(status_code=403, detail="이메일 인증이 필요합니다. 가입 시 등록한 이메일에서 인증을 완료해 주세요.")
            user_agent = request.headers.get("user-agent", "")
            token = create_session(db_user.id, ip_address=client_ip, user_agent=user_agent)
            if client_ip:
                ips = db_user.recent_ips or []
                ips = [ip for ip in ips if ip != client_ip]
                ips.insert(0, client_ip)
                db_user.recent_ips = ips[:10]
                s.commit()
            log_admin_action(db_user.id, db_user.username, "login", ip_address=client_ip)
            resp = JSONResponse(_user_json(db_user))
            secure = APP_ENV != "development"
            resp.set_cookie(key="session", value=token, max_age=30*86400, httponly=True, samesite="lax", path="/", secure=secure)
            resp.set_cookie(key="csrf_token", value=generate_csrf_token(db_user.id), max_age=3600, httponly=False, samesite="lax", path="/", secure=secure)
            return resp
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Login error")
        raise HTTPException(status_code=500, detail="Internal server error")


def _send_verification_email(u: User):
    if not SMTP_SERVER:
        if APP_ENV == "development":
            u.email_verified = True
            return
        logger.warning("SMTP not configured — email %s left unverified", u.email)
        return
    token = secrets.token_urlsafe(32)
    u.verification_token = token
    verify_url = f"{BASE_URL}/verify-email?token={token}"
    try:
        msg = MIMEText(
            f"안녕하세요, {u.display_name}님.\n\n"
            f"WRIT 계정 생성을 환영합니다. 아래 링크를 클릭하여 이메일 인증을 완료해 주세요.\n\n"
            f"{verify_url}\n\n"
            f"이 링크는 24시간 동안 유효합니다.\n감사합니다.\nWRIT 팀"
        )
        msg["Subject"] = "[WRIT] 이메일 인증을 완료해 주세요"
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
        logger.exception("Failed to send verification email to %s", u.email)


@router.post("/auth/register")
def api_register(request: Request, username: str = Form(...), password: str = Form(...),
                 display_name: str = Form(""), email: str = Form(...)):
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0].strip()
    if not _check_auth_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    display_handle = username
    username = username.lower()
    if username in RESERVED_HANDLES:
        raise HTTPException(status_code=400, detail="해당 아이디로 가입할 수 없습니다.")
    if not username or not password or not email:
        raise HTTPException(status_code=400, detail="Username, password, and email required")
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="Username (3+) and password (6+) required")
    if not re.match(r'^[a-z0-9][a-z0-9_]{2,19}$', username):
        raise HTTPException(status_code=400, detail="아이디는 영문 소문자, 숫자, 언더바만 사용 가능하며 3~20자입니다.")
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    with get_session() as s:
        existing = s.query(User).filter_by(username=username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        existing_email = s.query(User).filter_by(email=email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")
        domain = email.split("@")[-1] if "@" in email else ""
        if domain:
            blocked = s.query(BlockedDomain).filter_by(domain=domain).first()
            if blocked:
                raise HTTPException(status_code=400, detail="해당 이메일 도메인은 가입이 차단되었습니다.")
        user_count = s.query(User).count()
        is_first = user_count == 0
        if is_first and INITIAL_OWNER_PASSWORD and password != INITIAL_OWNER_PASSWORD:
            raise HTTPException(status_code=400, detail="초기 관리자 암호가 일치하지 않습니다.")
        salt, pwd_hash = hash_password(password)
        priv_key, pub_key = generate_keypair()
        email_verified = APP_ENV == "development"
        user = User(
            username=username,
            display_name=display_name or display_handle,
            display_handle=display_handle,
            password_hash=salt + ":" + pwd_hash,
            private_key=encrypt_key(priv_key, SECRET_KEY), public_key=pub_key,
            is_remote=False,
            role="owner" if is_first else "user",
            is_admin=is_first,
            email=email,
            email_verified=email_verified,
        )
        s.add(user)
        client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0].strip()
        if client_ip:
            user.recent_ips = [client_ip]
        s.flush()
        user_id = user.id

        try:
            _send_verification_email(user)
        except Exception:
            pass
        s.commit()

        log_admin_action(user_id, user.username, "register", ip_address=client_ip, details="first_user" if is_first else "email_required")

        return {"email_sent": True}


@router.post("/auth/verify-email")
def api_verify_email(request: Request, token: str = Form(...)):
    with get_session() as s:
        u = s.query(User).filter_by(verification_token=token).first()

        if not u:
            raise HTTPException(status_code=400, detail="유효하지 않거나 이미 만료된 인증 토큰입니다.")

        u.email_verified = True
        u.verification_token = ""

        # Notify admins/moderators about newly verified user
        if u.role != "owner":
            admins = s.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
            for admin in admins:
                if admin.id == u.id:
                    continue
                s.add(Notification(
                    user_id=admin.id, from_user_id=u.id,
                    notification_type="moderation",
                    metadata_json=json.dumps({"type": "new_user", "user_id": u.id, "username": u.username, "display_name": u.display_name}),
                ))

        s.commit()
        resp = JSONResponse({"ok": True, "email_verified": True})
        return resp


@router.post("/auth/resend-verification")
def api_resend_verification(request: Request, email: str = Form(...)):
    with get_session() as s:
        u = s.query(User).filter_by(email=email, email_verified=False).first()
        if not u:
            raise HTTPException(status_code=400, detail="해당 이메일로 등록된 인증 대기 계정이 없습니다.")
        _send_verification_email(u)
        s.commit()
        return {"ok": True, "email_sent": True}


@router.post("/auth/forgot-password")
def api_forgot_password(request: Request, email: str = Form(...)):
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0].strip()
    if not _check_auth_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    with get_session() as s:
        u = s.query(User).filter_by(email=email, is_remote=False).first()
        if not u or not SMTP_SERVER:
            return {"ok": True}
        token = secrets.token_urlsafe(32)
        u.reset_token = token
        s.commit()
        reset_url = f"{BASE_URL}/reset-password?token={token}"
        try:
            msg = MIMEText(
                f"안녕하세요, {u.display_name or u.username}님.\n\n"
                f"WRIT 비밀번호 재설정 요청을 받았습니다.\n"
                f"아래 링크를 클릭하여 새 비밀번호를 설정해 주세요.\n\n"
                f"{reset_url}\n\n"
                f"이 링크는 1시간 동안 유효합니다.\n"
                f"요청하지 않으셨다면 이 메일을 무시해 주세요.\n\n"
                f"감사합니다.\nWRIT 팀"
            )
            msg["Subject"] = "[WRIT] 비밀번호 재설정"
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
                    smtp.starttls()
                    if SMTP_USER:
                        smtp.login(SMTP_USER, SMTP_PASSWORD or "")
                    smtp.send_message(msg)
        except Exception:
            logger.exception("Failed to send password reset email to %s", u.email)
    return {"ok": True}


@router.post("/auth/reset-password")
def api_reset_password(request: Request, token: str = Form(...), password: str = Form(...)):
    with get_session() as s:
        u = s.query(User).filter_by(reset_token=token, is_remote=False).first()
        if not u:
            raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 토큰입니다.")
        salt, hval = hash_password(password)
        u.password_hash = f"{salt}:{hval}"
        u.reset_token = ""
        s.commit()
    return {"ok": True, "password_reset": True}


@router.post("/auth/logout")
def api_logout(request: Request):
    session_key = get_session_key_from_cookie(request)
    if session_key:
        delete_session_by_key(session_key)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    resp.delete_cookie("csrf_token")
    return resp


# ── Timeline API ──

@router.get("/timeline/stream")
async def api_timeline_stream(request: Request, tl_type: str = "home"):
    user = require_auth(request)
    if tl_type not in TIMELINE_LABELS:
        tl_type = "home"
    sid, q = add_stream(user.id, tl_type)
    async def event_gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
        finally:
            remove_stream(sid)
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


def _broadcast_update_actor(user):
    """Deliver Update actor activity to remote followers (background thread)."""
    try:
        update = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{user.actor_uri()}#updates/{uuid.uuid4()}",
            "type": "Update",
            "actor": user.actor_uri(),
            "object": to_ap_actor(user),
        }
        broadcast_to_followers(user, update)
    except Exception as e:
        logger.error("Failed to broadcast Update actor: %s", e, exc_info=True)


@router.post("/pin/series/{novel_id}")
def api_pin_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel or novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Series not found")
        pinned = list(user.pinned_series or [])
        if novel_id in pinned:
            return {"ok": True}
        if len(pinned) >= 3:
            raise HTTPException(status_code=400, detail="최대 3개까지 고정할 수 있습니다.")
        pinned.append(novel_id)
        s.query(User).filter_by(id=user.id).update({"pinned_series": pinned})
        s.commit()
    return {"ok": True}


@router.post("/unpin/series/{novel_id}")
def api_unpin_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        pinned = list(user.pinned_series or [])
        if novel_id in pinned:
            pinned.remove(novel_id)
            s.query(User).filter_by(id=user.id).update({"pinned_series": pinned})
            s.commit()
    return {"ok": True}


# ── User / Profile API ──

@router.get("/search/users")
def api_users_autocomplete(request: Request, q: str = Query("")):
    user = get_current_user(request)
    query = q.strip().lstrip("@")
    if not query:
        return {"users": []}
    with get_session() as s:
        pattern = f"{query}%"
        matches = s.query(User).filter(
            User.username.ilike(pattern),
        ).limit(5).all()
        if not matches:
            return {"users": []}
        following_ids = {f.following_id for f in s.query(Follow).filter_by(
            follower_id=user.id, accepted=True
        ).all()} if user else set()
        mentioned_ids = set()
        if user:
            recent_posts = s.query(Post.mentioned_user_ids).filter(
                Post.author_id == user.id,
                Post.mentioned_user_ids != None,
            ).order_by(desc(Post.created_at)).limit(50).all()
            for row in recent_posts:
                mids = row[0]
                if isinstance(mids, list):
                    for mid in mids:
                        if isinstance(mid, int):
                            mentioned_ids.add(mid)
        match_ids = {m.id for m in matches}
        follows_mentioned = sorted(
            [m for m in matches if m.id in following_ids and m.id in mentioned_ids],
            key=lambda m: (m.display_name or m.username).lower()
        )
        follows_only = sorted(
            [m for m in matches if m.id in following_ids and m.id not in mentioned_ids],
            key=lambda m: (m.display_name or m.username).lower()
        )
        mentioned_only = sorted(
            [m for m in matches if m.id not in following_ids and m.id in mentioned_ids],
            key=lambda m: (m.display_name or m.username).lower()
        )
        others = sorted(
            [m for m in matches if m.id not in following_ids and m.id not in mentioned_ids],
            key=lambda m: (m.display_name or m.username).lower()
        )
        ordered = follows_mentioned + follows_only + mentioned_only + others
        return {"users": [_user_json(u) for u in ordered]}


@router.get("/search/series")
def api_search_series(request: Request, q: str = Query("")):
    user = get_current_user(request)
    query = q.strip()
    if not user:
        return {"series": []}
    with get_session() as s:
        qb = _apply_latest_activity_order(s.query(Novel).filter(
            or_(Novel.visibility.in_(["public", "unlisted"]), Novel.author_id == user.id)
        ), s)
        if query:
            qb = qb.filter(Novel.title.ilike(f"%{query}%"))
        novels = qb.limit(5).all()
        return {"series": [_novel_json(n, s) for n in novels]}


@router.get("/search/tags")
def api_recent_tags(request: Request, q: str = Query("")):
    user = get_current_user(request)
    query = q.strip().lstrip("#")
    if not query or not user:
        return {"tags": []}
    with get_session() as s:
        recent_posts = s.query(Post).filter(
            Post.author_id == user.id,
            Post.tag_list.any(),
        ).order_by(desc(Post.created_at)).limit(50).all()
        tag_names: set[str] = set()
        for p in recent_posts:
            for t in (p.tag_list or []):
                if query.lower() in t.name.lower():
                    tag_names.add(t.name)
        ordered = sorted(tag_names, key=lambda n: n.lower().startswith(query.lower()), reverse=True)[:5]
        return {"tags": [{"name": t} for t in ordered]}


@router.get("/users/{username}")
def api_get_profile(request: Request, username: str, offset: int = 0, limit: int = 10):
    user = get_current_user(request)
    if "@" in username:
        parts = username.split("@")
        if len(parts) == 2:
            remote_user, remote_domain = parts
            actor_url = f"https://{remote_domain}/@{remote_user}"
            # Fire-and-forget: don't block profile load on remote actor refresh
            try:
                threading.Thread(target=_resolve_actor, args=(actor_url,), daemon=True).start()
            except Exception:
                pass
    with get_session() as s:
        profile = s.query(User).filter_by(username=username).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        is_deactivated = getattr(profile, 'is_deactivated', False) or False
        is_viewer_owner = user and profile.id == user.id
        if is_deactivated and not is_viewer_owner:
            return {
                "profile": _user_json(profile),
                "posts": [],
                "novels": [],
                "followers": [],
                "following": [],
                "total_posts": 0,
                "followers_count": 0,
                "following_count": 0,
                "is_following": False,
                "is_follow_pending": False,
                "has_pending_follower": False,
                "is_follower": False,
                "is_mine": False,
                "is_muted": False,
                "is_blocked": False,
                "am_i_blocked": False,
                "has_more": False,
                "offset": offset,
                "pinned_posts_data": [],
                "pinned_series_data": [],
            }
        boosted_ids = [b.post_id for b in s.query(Boost).filter_by(user_id=profile.id).all()]
        boost_subq = select(Boost.created_at).where(
            Boost.user_id == profile.id, Boost.post_id == Post.id
        ).correlate(Post).scalar_subquery()
        posts = s.query(Post).options(
            selectinload(Post.author)
        ).filter(
            or_(
                Post.author_id == profile.id,
                Post.id.in_(boosted_ids),
            ),
            Post.is_deleted == False,
        ).order_by(
            desc(func.coalesce(boost_subq, Post.created_at))
        ).offset(offset).limit(limit + 1).all()
        has_more = len(posts) > limit
        posts = [p for p in posts[:limit] if _can_view(p, user, s)]
        # Deduplicate: prioritize original posts over boost pointers
        seen_ids = set()
        deduped = []
        pending_boosts = {}
        for p in posts:
            if p.boost_of_id:
                # Keep the last one encountered (= oldest in DESC order)
                pending_boosts[p.boost_of_id] = p
            elif p.id in seen_ids:
                continue
            else:
                seen_ids.add(p.id)
                deduped.append(p)
        for boost_of_id, bp in pending_boosts.items():
            inserted = False
            for i, d in enumerate(deduped):
                if d.id == boost_of_id:
                    deduped.insert(i + 1, bp)
                    inserted = True
                    break
            if not inserted:
                deduped.append(bp)
        posts = deduped
        total_posts = s.query(Post).filter(
            or_(
                Post.author_id == profile.id,
                Post.id.in_(boosted_ids),
            ),
            Post.is_deleted == False,
        ).count()
        followers_count = s.query(Follow).filter_by(following_id=profile.id, accepted=True).count()
        following_count = s.query(Follow).filter_by(follower_id=profile.id, accepted=True).count()
        is_muted = s.query(UserMute).filter_by(user_id=user.id, target_user_id=profile.id).first() is not None if user else False
        is_blocked = s.query(UserBlock).filter_by(user_id=user.id, target_user_id=profile.id).first() is not None if user else False
        am_i_blocked = s.query(UserBlock).filter_by(user_id=profile.id, target_user_id=user.id).first() is not None if user else False
        is_following = s.query(Follow).filter_by(
            follower_id=user.id, following_id=profile.id, accepted=True
        ).first() is not None if user else False
        is_follow_pending = s.query(Follow).filter_by(
            follower_id=user.id, following_id=profile.id, accepted=False
        ).first() is not None if user else False
        notify_on_post = False
        if is_following and user:
            follow_rel = s.query(Follow).filter_by(
                follower_id=user.id, following_id=profile.id, accepted=True
            ).first()
            if follow_rel:
                notify_on_post = follow_rel.notify_on_post
        has_pending_follower = s.query(Follow).filter_by(
            follower_id=profile.id, following_id=user.id, accepted=False
        ).first() is not None if user else False
        is_follower = s.query(Follow).filter_by(
            follower_id=profile.id, following_id=user.id, accepted=True
        ).first() is not None if user else False
        novels_q = s.query(Novel).filter_by(author_id=profile.id)
        if not user or profile.id != user.id:
            novels_q = novels_q.filter(Novel.visibility != "private")
        novels = _apply_latest_activity_order(novels_q, s).all()
        show_follows = user and (profile.id == user.id or profile.follow_list_visibility != "private")
        followers = s.query(Follow).filter_by(following_id=profile.id, accepted=True).order_by(desc(Follow.created_at)).limit(20).all() if show_follows else []
        following = s.query(Follow).filter_by(follower_id=profile.id, accepted=True).order_by(desc(Follow.created_at)).limit(20).all() if show_follows else []
        # Batch-load _post_json data for all profile posts
        _all_post_ids = {p.id for p in posts}
        for _p in posts:
            if _p.boost_of_id:
                _all_post_ids.add(_p.boost_of_id)
        _all_post_ids = list(_all_post_ids | set(profile.pinned_posts or []))
        if user and _all_post_ids:
            _liked_ids = {l.post_id for l in s.query(Like).filter(Like.user_id == user.id, Like.post_id.in_(_all_post_ids)).all()}
            _boosted_ids = {b.post_id for b in s.query(Boost).filter(Boost.user_id == user.id, Boost.post_id.in_(_all_post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(_all_post_ids)).all()}
            _vote_map = {}
            for v in s.query(Vote).filter(Vote.user_id == user.id, Vote.post_id.in_(_all_post_ids)).all():
                _vote_map[v.post_id] = v.option_index
            _my_reaction_map = {}
            for l in s.query(Like).filter(Like.user_id == user.id, Like.post_id.in_(_all_post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[l.post_id] = l.reaction
            _reactions_map = {}
            for pid, react, cnt in s.query(Like.post_id, func.coalesce(Like.reaction, "★"), func.count(Like.id)).filter(Like.post_id.in_(_all_post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all():
                if pid not in _reactions_map:
                    _reactions_map[pid] = {}
                _reactions_map[pid][react] = cnt
            # Batch-load booster info to avoid N+1 queries in _post_json
            # On profile page, only show boosts by the profile user
            _booster_map = {}
            _three_hours_ago = datetime.now(timezone.utc) - timedelta(seconds=10800)
            _boost_rows = s.query(Boost).filter(
                Boost.post_id.in_(_all_post_ids),
                Boost.user_id == profile.id,
                Boost.created_at > _three_hours_ago,
            ).order_by(desc(Boost.created_at)).all()
            _booster_user_ids = {b.user_id for b in _boost_rows}
            _booster_users = {u.id: u for u in s.query(User).filter(User.id.in_(_booster_user_ids)).all()} if _booster_user_ids else {}
            for b in _boost_rows:
                if b.post_id not in _booster_map:
                    _booster_map[b.post_id] = _booster_users.get(b.user_id)
            all_mentioned_ids = set()
            _posts_for_mentions = s.query(Post).filter(Post.id.in_(_all_post_ids)).all()
            for pp in _posts_for_mentions:
                if pp.mentioned_user_ids:
                    all_mentioned_ids.update(pp.mentioned_user_ids)
            _mentioned_users_map = {}
            if all_mentioned_ids:
                _mu = {}
                for _um in s.query(User).filter(User.id.in_(all_mentioned_ids)).all():
                    if _um.is_remote and _um.remote_url:
                        _name = _um.username.split("@")[0]
                        _domain = urlparse(_um.remote_url).hostname or ""
                        _mu[_um.id] = f"{_name}@{_domain}"
                    else:
                        _mu[_um.id] = _um.username
                for pp in _posts_for_mentions:
                    if pp.mentioned_user_ids:
                        _mentioned_users_map[pp.id] = [_mu.get(mid, "?") for mid in pp.mentioned_user_ids if mid in _mu]
                    else:
                        _mentioned_users_map[pp.id] = []
        else:
            _liked_ids = _boosted_ids = _bookmarked_ids = set()
            _vote_map = _my_reaction_map = _reactions_map = _mentioned_users_map = _booster_map = {}
        _pj_kwargs = dict(_liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids,
                          _vote_map=_vote_map, _my_reaction_map=_my_reaction_map,
                          _reactions_map=_reactions_map, _booster_map=_booster_map,
                          _mentioned_users_map=_mentioned_users_map)
        return {
            "profile": _user_json(profile),
            "posts": [_post_json(p, s, user, **_pj_kwargs) for p in posts],
            "novels": [_novel_json(n, s) for n in novels],
            "followers": [{"user": _user_json(f.follower)} for f in (followers if show_follows else [])],
            "following": [{"user": _user_json(f.following)} for f in (following if show_follows else [])],
            "total_posts": total_posts,
            "followers_count": followers_count if show_follows else 0,
            "following_count": following_count if show_follows else 0,
            "is_following": is_following,
            "is_follow_pending": is_follow_pending,
            "notify_on_post": notify_on_post,
            "has_pending_follower": has_pending_follower,
            "is_follower": is_follower,
            "is_mine": profile.id == user.id if user else False,
            "is_muted": is_muted,
            "is_blocked": is_blocked,
            "am_i_blocked": am_i_blocked,
            "has_more": has_more,
            "offset": offset,
            "pinned_posts_data": [_post_json(p, s, user, **_pj_kwargs) for p in (s.query(Post).filter(Post.id.in_(profile.pinned_posts or []), Post.is_deleted == False).all() if profile.pinned_posts else []) if _can_view(p, user, s)],
            "pinned_series_data": [_novel_json(n, s) for n in (s.query(Novel).filter(Novel.id.in_(profile.pinned_series or [])).all() if profile.pinned_series else [])],
        }


@router.get("/users/{username}/media")
def api_user_media(request: Request, username: str, limit: int = Query(12), offset: int = Query(0)):
    user = get_current_user(request)
    with get_session() as s:
        profile = s.query(User).filter_by(username=username).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        # Use raw SQL to filter non-empty media_attachments at DB level (cast to text for cross-DB compatibility)
        rows = s.execute(
            text("SELECT id FROM posts WHERE author_id = :aid AND is_deleted = FALSE AND CAST(media_attachments AS TEXT) NOT IN ('null', '[]') ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
            {"aid": profile.id, "lim": limit + 1, "off": offset}
        ).fetchall()
        post_ids = [r[0] for r in rows]
        has_more = len(post_ids) > limit
        post_ids = post_ids[:limit]
        if not post_ids:
            return {"posts": [], "has_more": False}
        posts = s.query(Post).options(selectinload(Post.author)).filter(Post.id.in_(post_ids)).all()
        posts = sorted(posts, key=lambda p: post_ids.index(p.id))
        # Count total for has_more if needed
        if not has_more:
            total = s.execute(
                text("SELECT COUNT(*) FROM posts WHERE author_id = :aid AND is_deleted = FALSE AND CAST(media_attachments AS TEXT) NOT IN ('null', '[]')"),
                {"aid": profile.id}
            ).scalar()
            has_more = total > offset + limit
        return {"posts": [_post_json(p, s, user) for p in posts if _can_view(p, user, s)], "has_more": has_more}


@router.post("/users/{username}/follow")
def api_follow(request: Request, username: str):
    user = require_active_auth(request)
    if "@" in username and not username.startswith("@"):
        remote_username = username
        with get_session() as s:
            target = s.query(User).filter_by(username=remote_username).first()
            if not target:
                parts = remote_username.split("@")
                if len(parts) == 2:
                    actor_url = f"https://{parts[1]}/@{parts[0]}"
                    target = _resolve_actor(actor_url)
            if not target or not target.is_remote:
                raise HTTPException(status_code=404, detail="Remote user not found")
            existing = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
            if not existing:
                remote_obj = target.actor_uri()
                follow_activity = {
                    "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
                    "id": f"{BASE_URL}/activities/follow/{uuid.uuid4()}",
                    "type": "Follow",
                    "actor": user.actor_uri(),
                    "object": remote_obj,
                    "to": [remote_obj],
                }
                s.add(Follow(follower_id=user.id, following_id=target.id, accepted=False, activity_id=follow_activity["id"]))
                s.commit()
                inbox = target.inbox_url
                if inbox:
                    _post_to_inbox(inbox, follow_activity, user)
        return {"ok": True}

    with get_session() as s:
        target = s.query(User).filter_by(username=username, is_remote=False).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        if target.id == user.id:
            raise HTTPException(status_code=400, detail="Cannot follow yourself")
        existing = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
        if not existing:
            accepted = not target.is_locked
            s.add(Follow(follower_id=user.id, following_id=target.id, accepted=accepted))
            existing_notif = s.query(Notification).filter_by(
                from_user_id=user.id, user_id=target.id
            ).filter(Notification.notification_type.in_(["follow", "follow_request"])).first()
            if not existing_notif:
                s.add(Notification(user_id=target.id, from_user_id=user.id, notification_type="follow_request" if not accepted else "follow"))
            s.commit()
            broadcast_refresh_notifs(target.id)
            send_push_to_user(target.id, "follow" if accepted else "follow_request", user.username)
            broadcast_notif_sound(target.id)
    return {"ok": True}


@router.post("/users/{username}/approve-follow")
def api_approve_follow(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(Follow).filter_by(
            following_id=user.id
        ).join(User, Follow.follower_id == User.id).filter(User.username == username).first()
        if not target:
            raise HTTPException(status_code=404, detail="Follow request not found")
        follower = s.query(User).get(target.follower_id)
        follower_is_remote = follower and follower.is_remote
        target.accepted = True
        s.query(Notification).filter_by(
            from_user_id=target.follower_id, user_id=user.id, notification_type="follow_request"
        ).update({"notification_type": "follow"})
        s.commit()
        if follower_is_remote and follower:
            try:
                follow_activity_id = target.activity_id or f"{follower.actor_uri()}#follows/{user.id}"
                inbox = follower.inbox_url or (follower.actor_uri().rstrip("/") + "/inbox")
                _send_accept(inbox, follow_activity_id, user, follower=follower)
            except Exception as e:
                logger.error("Failed to send Accept: %s", e, exc_info=True)
    return {"ok": True}

@router.post("/users/{username}/remove-follower")
def api_remove_follower(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        follower = s.query(User).filter_by(username=username).first()
        if not follower:
            raise HTTPException(status_code=404, detail="User not found")
        follow = s.query(Follow).filter_by(
            follower_id=follower.id, following_id=user.id
        ).first()
        if not follow:
            raise HTTPException(status_code=404, detail="Not following you")
        s.query(Notification).filter(
            Notification.from_user_id == follower.id,
            Notification.user_id == user.id,
            Notification.notification_type.in_(["follow", "follow_request"])
        ).delete(synchronize_session=False)
        s.delete(follow)
        s.commit()
        try:
            broadcast_refresh_notifs(user.id)
        except Exception:
            pass
    return {"ok": True}

@router.get("/follow-requests")
def api_list_follow_requests(request: Request):
    user = require_auth(request)
    with get_session() as s:
        pending = s.query(Follow).filter_by(following_id=user.id, accepted=False).all()
        return {"requests": [{"id": f.id, "user": _user_json(f.follower)} for f in pending]}


@router.post("/users/{username}/reject-follow")
def api_reject_follow(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(Follow).filter_by(
            following_id=user.id
        ).join(User, Follow.follower_id == User.id).filter(User.username == username).first()
        if not target:
            raise HTTPException(status_code=404, detail="Follow request not found")
        follower = s.query(User).get(target.follower_id)
        follower_is_remote = follower and follower.is_remote
        s.query(Notification).filter_by(
            from_user_id=target.follower_id, user_id=user.id, notification_type="follow_request"
        ).delete()
        s.delete(target)
        s.commit()
        try:
            broadcast_refresh_notifs(user.id)
        except Exception:
            pass
        if follower_is_remote and follower:
            try:
                follow_activity_id = f"{follower.actor_uri()}#follows/{user.id}"
                inbox = follower.inbox_url or (follower.actor_uri().rstrip("/") + "/inbox")
                _send_reject(inbox, follow_activity_id, user, follower_actor_url=follower.actor_uri())
            except Exception as e:
                logger.error("Failed to send Reject: %s", e, exc_info=True)
    return {"ok": True}

@router.post("/users/{username}/unfollow")
def api_unfollow(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        existing = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
        if existing:
            s.delete(existing)
            s.query(Notification).filter(
                Notification.from_user_id == user.id,
                Notification.user_id == target.id,
                Notification.notification_type.in_(["follow", "follow_request"])
            ).delete(synchronize_session=False)
            s.commit()
            try:
                broadcast_refresh_notifs(target.id)
            except Exception:
                pass
            if target.is_remote and target.inbox_url:
                follow_activity_id = f"{user.actor_uri()}#follows/{target.id}"
                undo = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{user.actor_uri()}#follows/{target.id}/undo",
                    "type": "Undo",
                    "actor": user.actor_uri(),
                    "object": {
                        "id": follow_activity_id,
                        "type": "Follow",
                        "actor": user.actor_uri(),
                        "object": target.actor_uri(),
                    },
                }
                try:
                    _post_to_inbox(target.inbox_url, undo, user)
                except Exception as e:
                    logger.error("Failed to send Undo Follow: %s", e, exc_info=True)
    return {"ok": True}


@router.post("/users/{username}/toggle-notify")
def api_toggle_notify(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        follow = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
        if not follow:
            raise HTTPException(status_code=404, detail="Not following this user")
        follow.notify_on_post = not follow.notify_on_post
        s.commit()
        return {"ok": True, "notify_on_post": follow.notify_on_post}


@router.get("/users/{username}/followers")
def api_followers(request: Request, username: str):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        target = s.query(User).filter_by(username=username, is_remote=False).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        follows = s.query(Follow).filter_by(following_id=target.id, accepted=True).order_by(desc(Follow.created_at)).all()
        users = [s.query(User).get(f.follower_id) for f in follows]
    return {"users": [_user_json(u) for u in users if u]}


@router.get("/users/{username}/following")
def api_following(request: Request, username: str):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        target = s.query(User).filter_by(username=username, is_remote=False).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        follows = s.query(Follow).filter_by(follower_id=target.id, accepted=True).order_by(desc(Follow.created_at)).all()
        users = [s.query(User).get(f.following_id) for f in follows]
    return {"users": [_user_json(u) for u in users if u]}


# ── Notifications API ──

@router.get("/direct/conversation/{other_id}")
def api_direct_conversation(request: Request, other_id: int):
    user = require_auth(request)
    is_self = (other_id == user.id)
    with get_session() as s:
        if is_self:
            other = user
        else:
            other = s.query(User).get(other_id)
            if not other:
                raise HTTPException(status_code=404, detail="User not found")
        _contains_self = _json_array_has_user(Post.mentioned_user_ids, user.id)
        _contains_other = _json_array_has_user(Post.mentioned_user_ids, other_id)
        if is_self:
            conv_posts = s.query(Post).options(selectinload(Post.author)).filter(
                Post.visibility == "mention",
                Post.is_deleted == False,
                Post.author_id == user.id,
                _contains_self,
            ).order_by(Post.created_at).all()
        else:
            conv_posts = s.query(Post).options(selectinload(Post.author)).filter(
                Post.visibility == "mention",
                Post.is_deleted == False,
                or_(
                    and_(Post.author_id == user.id, _contains_other),
                    and_(Post.author_id == other_id, _contains_self),
                ),
            ).order_by(Post.created_at).all()
        result = {
            "other_user": _user_json(other),
            "messages": [_post_json(p, s, user) for p in conv_posts],
        }
    return result


@router.get("/notifications/direct-threads")
def api_direct_threads(request: Request):
    user = require_auth(request)
    three_months_ago = datetime.now(timezone.utc) - timedelta(days=90)
    with get_session() as s:
        posts = s.query(Post).filter(
            Post.visibility == "mention",
            Post.is_deleted == False,
            Post.created_at >= three_months_ago,
            or_(
                Post.author_id == user.id,
                _json_array_has_user(Post.mentioned_user_ids, user.id),
            ),
        ).order_by(desc(Post.created_at)).limit(200).all()
        author_map = {}
        for p in posts:
            mu = p.mentioned_user_ids or []
            other_id = None
            if p.author_id == user.id:
                for tid in mu:
                    if isinstance(tid, int):
                        if tid == user.id and (p.author_id == user.id):
                            other_id = user.id
                            break
                        elif tid != user.id:
                            other_id = tid
                            break
            elif user.id in mu:
                other_id = p.author_id
            if other_id is not None and other_id not in author_map:
                if other_id == user.id:
                    author_map[other_id] = {"user": user, "all_msgs": []}
                else:
                    author = s.query(User).get(other_id)
                    author_map[other_id] = {"user": author, "all_msgs": []}
            if other_id is not None:
                author_map[other_id]["all_msgs"].append(p)
        result = []
        for aid, data in author_map.items():
            u = data["user"]
            sorted_msgs = sorted(data["all_msgs"], key=lambda x: x.created_at or datetime.min, reverse=True)
            previews = []
            for msg in sorted_msgs[:3]:
                text = re.sub(r'<[^>]*>', '', msg.content or "")
                text = re.sub(r'@\w+', '', text).strip()
                is_me = msg.author_id == user.id
                previews.append({"text": text[:60], "is_me": is_me})
            entry = _user_json(u)
            entry["latest_previews"] = previews
            entry["latest_time"] = _fmt_dt(sorted_msgs[0].created_at)
            result.append(entry)
    return {"users": result}


def _generate_poll_end_notifications(user_id: int, session):
    now = datetime.now(timezone.utc)
    # 빠른 확인: 사용자의 poll이 없으면 skip
    has_any_poll = session.query(Post.id).filter(
        Post.poll_data.isnot(None), Post.is_deleted == False,
        Post.author_id == user_id,
    ).first() is not None
    has_voted_poll = session.query(Post.id).join(Vote, Vote.post_id == Post.id).filter(
        Vote.user_id == user_id, Post.poll_data.isnot(None), Post.is_deleted == False
    ).first() is not None
    if not has_any_poll and not has_voted_poll:
        return
    candidates = []
    if has_voted_poll:
        voted_posts = (
            session.query(Post)
            .join(Vote, Vote.post_id == Post.id)
            .filter(Vote.user_id == user_id, Post.poll_data.isnot(None), Post.is_deleted == False)
            .limit(50)
            .all()
        )
        candidates.extend(voted_posts)
    if has_any_poll:
        authored_posts = (
            session.query(Post)
            .filter(Post.author_id == user_id, Post.poll_data.isnot(None), Post.is_deleted == False)
            .limit(50)
            .all()
        )
        for p in authored_posts:
            if p not in candidates and len(candidates) < 100:
                candidates.append(p)
    for post in candidates:
        expires_at = post.poll_data.get("expires_at") if post.poll_data else None
        if not expires_at:
            continue
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                continue
        except (ValueError, TypeError):
            continue
        existing = (
            session.query(Notification)
            .filter_by(user_id=user_id, notification_type="poll_ended", post_id=post.id)
            .first()
        )
        if not existing:
            session.add(Notification(
                user_id=user_id,
                from_user_id=post.author_id,
                notification_type="poll_ended",
                post_id=post.id,
                metadata_json=json.dumps({"is_author": post.author_id == user_id}),
            ))
    session.commit()


@router.get("/notifications")
def api_notifications(request: Request, filter_type: str = Query(""), limit: int = Query(20), offset: int = Query(0), mark_read: bool = Query(True)):
    limit = min(limit, 20)
    user = require_auth(request)
    with get_session() as s:
        # 첫 페이지에서만 투표 마감 알림 생성
        if offset == 0:
            _generate_poll_end_notifications(user.id, s)

        q = s.query(Notification).options(
            selectinload(Notification.from_user),
            selectinload(Notification.post).selectinload(Post.author),
        ).filter_by(user_id=user.id)
        if filter_type == "follow":
            q = q.filter(Notification.notification_type.in_(["follow", "follow_request"]))
        elif filter_type == "vote":
            q = q.filter(Notification.notification_type.in_(["vote", "poll_ended"]))
        elif filter_type:
            q = q.filter_by(notification_type=filter_type)
        q = q.order_by(desc(Notification.created_at))
        raw = q.offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        notifs = raw[:limit]

        # 이미 로드된 Notification.post 객체를 재사용 (재조회 제거)
        posts_cache = [n.post for n in notifs if n.post and not n.post.is_deleted]
        notif_post_ids = [p.id for p in posts_cache]

        _liked_ids = _boosted_ids = _bookmarked_ids = set()
        _vote_map = {}
        _my_reaction_map = {}
        _reactions_map = {}
        _mentioned_users_map = {}
        _booster_map = {}

        if user and notif_post_ids:
            _liked_ids = {l.post_id for l in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(notif_post_ids)).all()}
            _boosted_ids = {b.post_id for b in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(notif_post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(notif_post_ids)).all()}

            for v in s.query(Vote.post_id, Vote.option_index).filter(Vote.user_id == user.id, Vote.post_id.in_(notif_post_ids)).all():
                _vote_map[v.post_id] = v.option_index

            for l in s.query(Like.post_id, Like.reaction).filter(Like.user_id == user.id, Like.post_id.in_(notif_post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[l.post_id] = l.reaction

            for bid, buid in s.query(Boost.post_id, Boost.user_id).filter(Boost.post_id.in_(notif_post_ids)).order_by(desc(Boost.created_at)).all():
                if bid not in _booster_map:
                    _booster_map[bid] = buid
            if _booster_map:
                _booster_users = {u.id: u for u in s.query(User).filter(User.id.in_(set(_booster_map.values()))).all()}
                _booster_map = {pid: _booster_users.get(uid) for pid, uid in _booster_map.items()}

            for pid, react, cnt in s.query(Like.post_id, func.coalesce(Like.reaction, "★"), func.count(Like.id)).filter(Like.post_id.in_(notif_post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all():
                if pid not in _reactions_map:
                    _reactions_map[pid] = {}
                _reactions_map[pid][react] = cnt

            # posts_cache를 활용해 DB 재조회 제거
            all_mentioned_ids = set()
            for p in posts_cache:
                if p.mentioned_user_ids:
                    all_mentioned_ids.update(p.mentioned_user_ids)

            if all_mentioned_ids:
                _mentioned_users = {}
                for _um in s.query(User).filter(User.id.in_(all_mentioned_ids)).all():
                    if _um.is_remote and _um.remote_url:
                        _name = _um.username.split("@")[0]
                        _domain = urlparse(_um.remote_url).hostname or ""
                        _mentioned_users[_um.id] = f"{_name}@{_domain}"
                    else:
                        _mentioned_users[_um.id] = _um.username
                for p in posts_cache:
                    if p.mentioned_user_ids:
                        _mentioned_users_map[p.id] = [_mentioned_users.get(mid, "?") for mid in p.mentioned_user_ids if mid in _mentioned_users]
                    else:
                        _mentioned_users_map[p.id] = []

        result = []
        for n in notifs:
            meta = {}
            if n.metadata_json:
                try: meta = json.loads(n.metadata_json)
                except: pass
            if n.notification_type == "like":
                _post_author = n.post.author if n.post else None
                _reactions_on = _post_author and getattr(_post_author, 'enable_reactions', True)
                if _reactions_on and not meta.get("reaction") and n.post and n.from_user_id:
                    _like_row = s.query(Like.reaction).filter(Like.user_id == n.from_user_id, Like.post_id == n.post_id).first()
                    if _like_row and _like_row[0]:
                        meta = {"reaction": _like_row[0]}
                    else:
                        meta = {"reaction": "★"}
                elif not _reactions_on and meta.get("reaction"):
                    meta = {}
            post = n.post
            item = {
                "id": n.id,
                "type": n.notification_type,
                "created_at": _fmt_dt(n.created_at),
                "is_read": n.is_read,
                "from_user": _user_json(n.from_user) if n.from_user else None,
                "post": _post_json(post, s, user,
                    _liked_ids=_liked_ids, _boosted_ids=_boosted_ids,
                    _bookmarked_ids=_bookmarked_ids, _vote_map=_vote_map,
                    _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map,
                    _booster_map=_booster_map, _mentioned_users_map=_mentioned_users_map,
                    _skip_emojis=True,
                ) if post and not post.is_deleted and _can_view(post, user, s) else None,
                "metadata": meta,
            }
            result.append(item)

        # 읽음 처리: 현재 페이지에 노출된 알림만 업데이트
        if offset == 0 and mark_read and notifs:
            unread_ids = [n.id for n in notifs if not n.is_read]
            if unread_ids:
                s.query(Notification).filter(Notification.id.in_(unread_ids)).update({"is_read": True}, synchronize_session=False)
                s.commit()
                _unread_cache.pop(user.id, None)

    return {"notifications": result, "has_more": has_more, "total": 0}


@router.get("/notifications/stream")
async def api_notifications_stream(request: Request):
    user = require_auth(request)
    sid, q = add_notif_stream(user.id)
    async def event_gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
        finally:
            remove_notif_stream(sid)
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


# ── Novels / Episodes API ──

@router.get("/profile-notes/{target_username}")
def api_get_profile_note(request: Request, target_username: str):
    user = require_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=target_username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        note = s.query(ProfileNote).filter_by(user_id=user.id, target_user_id=target.id).first()
        return {"content": note.content if note else ""}


@router.post("/profile-notes/{target_username}")
def api_save_profile_note(request: Request, target_username: str, content: str = Form("")):
    user = require_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=target_username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        note = s.query(ProfileNote).filter_by(user_id=user.id, target_user_id=target.id).first()
        if note:
            note.content = content
        else:
            s.add(ProfileNote(user_id=user.id, target_user_id=target.id, content=content))
        s.commit()
    return {"ok": True}


def _apply_latest_activity_order(q, s):
    latest_ep = s.query(
        Episode.novel_id, func.max(Episode.created_at).label("max_ep")
    ).group_by(Episode.novel_id).subquery()
    latest_nt = s.query(
        SeriesNotice.novel_id, func.max(SeriesNotice.created_at).label("max_nt")
    ).group_by(SeriesNotice.novel_id).subquery()
    q = q.outerjoin(latest_ep, Novel.id == latest_ep.c.novel_id)
    q = q.outerjoin(latest_nt, Novel.id == latest_nt.c.novel_id)
    q = q.order_by(desc(func.coalesce(latest_ep.c.max_ep, latest_nt.c.max_nt)).nullslast())
    return q

@router.get("/series")
def api_novels(request: Request, limit: int = Query(12), offset: int = Query(0)):
    with get_session() as s:
        q = _apply_latest_activity_order(s.query(Novel).filter_by(is_published=True, visibility="public"), s)
        raw = q.offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        novels = [_novel_json(n, s) for n in raw[:limit]]
        return {"novels": novels, "has_more": has_more}


@router.get("/series/my")
def api_my_novels(request: Request, limit: int = Query(12), offset: int = Query(0)):
    user = require_auth(request)
    with get_session() as s:
        q = _apply_latest_activity_order(s.query(Novel).filter_by(author_id=user.id), s)
        total = q.count()
        raw = q.offset(offset).limit(limit).all()
        novels = [_novel_json(n, s) for n in raw]
        return {"novels": novels, "total": total, "page": offset // limit + 1, "pages": max(1, (total + limit - 1) // limit)}


@router.get("/series/followed")
def api_followed_novels(request: Request, limit: int = Query(12), offset: int = Query(0)):
    user = require_auth(request)
    with get_session() as s:
        follow_ids = [f.novel_id for f in s.query(SeriesFollow).filter_by(user_id=user.id).all()]
        if not follow_ids:
            return {"novels": [], "total": 0, "page": 1, "pages": 1}
        q = _apply_latest_activity_order(
            s.query(Novel).filter(Novel.id.in_(follow_ids), Novel.is_published == True), s
        )
        total = q.count()
        raw = q.offset(offset).limit(limit).all()
        novels = [_novel_json(n, s) for n in raw]
        return {"novels": novels, "total": total, "page": offset // limit + 1, "pages": max(1, (total + limit - 1) // limit)}


def _sync_tags(n, s):
    raw = n.tags or ""
    desired = {}
    for t in raw.replace(",", " ").split():
        if t:
            desired[t.lower()] = t
    current = {t.name: t for t in (n.tag_list or [])}
    for lower_name, display in desired.items():
        if lower_name in current:
            tag = current[lower_name]
            if tag.display_name != display:
                tag.display_name = display
        else:
            tag = s.query(Tag).filter_by(name=lower_name).first()
            if not tag:
                tag = Tag(name=lower_name, display_name=display)
                s.add(tag)
                s.flush()
            else:
                tag.display_name = display
            n.tag_list.append(tag)
    for name in set(current.keys()) - set(desired.keys()):
        tag = current[name]
        n.tag_list.remove(tag)


def _novel_json(n, s=None, _followers_map=None):
    author = None
    if hasattr(n, 'author') and n.author:
        author = _user_json(n.author)
    tag_names = " ".join(t.display_name or t.name for t in (n.tag_list or [])) or (n.tags or "")
    result = {
        "id": n.id,
        "number": n.number or "",
        "title": n.title,
        "description": n.description or "",
        "cover_image": n.cover_image or "",
        "tags": tag_names,
        "status": n.status or "ongoing",
        "is_published": n.is_published,
        "is_sensitive": getattr(n, 'is_sensitive', False) or False,
        "episode_count": n.episode_count or 0,
        "total_views": n.total_views or 0,
        "visibility": n.visibility or "public",
        "created_at": _fmt_dt(n.created_at),
        "updated_at": _fmt_dt(n.updated_at),
        "author": author,
        "author_id": n.author_id,
    }
    if _followers_map is not None:
        result["followers_count"] = _followers_map.get(n.id, 0)
    elif s is not None:
        result["followers_count"] = s.query(SeriesFollow).filter_by(novel_id=n.id).count()
    return result


@router.post("/series/new")
def api_create_novel(request: Request, title: str = Form(...), description: str = Form(""),
                     tags: str = Form(""), visibility: str = Form("public"), status: str = Form("ongoing"),
                     cover_image: UploadFile = File(None), is_sensitive: bool = Form(False)):
    user = require_active_auth(request)
    is_user_deceased = False
    if isinstance(user, dict):
        is_user_deceased = user.get('is_deceased', False)
    else:
        is_user_deceased = getattr(user, 'is_deceased', False)

    if is_user_deceased:
        raise HTTPException(status_code=403, detail="고인 계정은 시리즈를 생성할 수 없습니다.")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    storage = get_storage()
    cover_url = ""
    if cover_image and cover_image.filename:
        ext, is_image, is_video = _validate_upload(cover_image, allow_video=False, max_size=MAX_AVATAR_SIZE, label="커버 이미지")
        ct = cover_image.content_type or ""
        if "gif" in ct:
            ext = "gif"
        key = f"series/covers/{uuid4().hex[:16]}.{ext}"
        img = Image.open(cover_image.file)
        target_w, target_h = 120, 160
        img_w, img_h = img.size
        ratio = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * ratio)
        new_h = int(img_h * ratio)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        out = io.BytesIO()
        img.save(out, format="WEBP" if ext != "gif" else "GIF", quality=90)
        cover_url = storage.save(key, out.getvalue(), f"image/{ext}")
    with get_session() as s:
        novel_number = secrets.token_hex(4)
        novel_status = status if status in ("ongoing", "hiatus", "discontinued", "completed") else "ongoing"
        novel = Novel(author_id=user.id, title=title, description=description, tags=tags,
                      visibility=visibility, is_published=visibility != "private", status=novel_status,
                      cover_image=cover_url, number=novel_number, is_sensitive=is_sensitive)
        s.add(novel)
        s.flush()
        _sync_tags(novel, s)
        nid = novel.id
        s.commit()
    return {"ok": True, "novel_id": nid}


@router.get("/series/{novel_id}")
def api_get_novel(request: Request, novel_id: int):
    user = get_current_user(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if novel.visibility == "private" and (not user or novel.author_id != user.id):
            raise HTTPException(status_code=404, detail="Novel not found")
        if not user and novel.visibility in ("public", "unlisted"):
            pass
        episodes = s.query(Episode).filter_by(novel_id=novel_id).order_by(Episode.episode_number).all()
        author = s.query(User).get(novel.author_id)
        is_mine = user.id == novel.author_id if user else False
        episode_list = [_episode_json(e, summary_only=True) for e in episodes]
        novel_json = _novel_json(novel, s)
        if not is_mine:
            for e in episode_list:
                e.pop("views", None)
            novel_json.pop("total_views", None)
        result = {
            "novel": novel_json,
            "episodes": episode_list,
            "author": _user_json(author) if author else None,
            "is_mine": user.id == novel.author_id if user else False,
            "is_following": s.query(SeriesFollow).filter_by(user_id=user.id, novel_id=novel.id).count() > 0 if user else False,
        }
    return result


@router.post("/series/{novel_id}/follow")
def api_follow_novel(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if novel.visibility == "private" and novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Novel not found")
        existing = s.query(SeriesFollow).filter_by(user_id=user.id, novel_id=novel.id).first()
        if not existing:
            sf = SeriesFollow(user_id=user.id, novel_id=novel.id)
            s.add(sf)
            s.commit()
    return {"ok": True}


@router.post("/series/{novel_id}/unfollow")
def api_unfollow_novel(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(SeriesFollow).filter_by(user_id=user.id, novel_id=novel_id).delete()
        s.commit()
    return {"ok": True}


@router.post("/series/{novel_id}/edit")
def api_edit_novel(request: Request, novel_id: int, title: str = Form(...), description: str = Form(""),
                   tags: str = Form(""), visibility: str = Form("public"), status: str = Form("ongoing"),
                   cover_image: UploadFile = File(None), remove_cover: bool = Form(False),
                   is_sensitive: bool = Form(False)):
    user = require_active_auth(request)
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    storage = get_storage()
    cover_url = ""
    if cover_image and cover_image.filename:
        ext, is_image, is_video = _validate_upload(cover_image, allow_video=False, max_size=MAX_AVATAR_SIZE, label="커버 이미지")
        ct = cover_image.content_type or ""
        if "gif" in ct:
            ext = "gif"
        key = f"series/covers/{uuid4().hex[:16]}.{ext}"
        img = Image.open(cover_image.file)
        target_w, target_h = 120, 160
        img_w, img_h = img.size
        ratio = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * ratio)
        new_h = int(img_h * ratio)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        out = io.BytesIO()
        img.save(out, format="WEBP" if ext != "gif" else "GIF", quality=90)
        cover_url = storage.save(key, out.getvalue(), f"image/{ext}")
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        novel.title = title
        novel.description = description
        novel.tags = tags
        novel.visibility = visibility
        novel.status = status if status in ("ongoing", "hiatus", "discontinued", "completed") else "ongoing"
        novel.is_published = visibility != "private"
        novel.is_sensitive = is_sensitive
        if remove_cover:
            old = novel.cover_image
            novel.cover_image = ""
            s.flush()
            if old and old.startswith("/"):
                storage.delete(old)
        if cover_url:
            old = novel.cover_image
            novel.cover_image = cover_url
            s.flush()
            if old and old.startswith("/"):
                storage.delete(old)
        s.flush()
        _sync_tags(novel, s)
        s.commit()
    return {"ok": True}


@router.post("/series/{novel_id}/episodes/new")
def api_create_episode(request: Request, novel_id: int, title: str = Form(...), content: str = Form(...),
                       summary: str = Form(""), comment: str = Form(""),
                       announce: bool = Form(False), announce_comment: str = Form(""),
                       is_published: bool = Form(True)):
    user = require_active_auth(request)
    if getattr(user, 'is_deceased', False):
        raise HTTPException(status_code=403, detail="고인 계정은 에피소드를 생성할 수 없습니다.")
    if not title.strip() or not content.strip():
        raise HTTPException(status_code=400, detail="Title and content are required")
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        max_ep = s.query(Episode).filter_by(novel_id=novel.id).order_by(desc(Episode.episode_number)).first()
        next_num = (max_ep.episode_number + 1) if max_ep else 1
        episode = Episode(novel_id=novel.id, episode_number=next_num, title=title, content=content, summary=summary, comment=comment, is_published=is_published)
        s.add(episode)
        s.flush()
        if announce:
            parts = []
            if announce_comment:
                parts.append(announce_comment)
            link = f'📖 <a href="/series/{novel.id}/episodes/{episode.id}">[{novel.title}] {next_num}화: {title}</a>'
            parts.append(link)
            if summary:
                parts.append(summary)
            post_content = "\n\n".join(parts)
            ep_post_number = secrets.token_hex(4)
            post = Post(
                author_id=user.id,
                content=post_content,
                visibility="public",
                number=ep_post_number,
                novel_id=novel.id,
                episode_id=episode.id,
                ap_id="",
            )
            s.add(post)
            s.flush()
            post.ap_id = f"{BASE_URL}/@{user.username}/{ep_post_number}"
            s.flush()
            try:
                s.refresh(post)
                create_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/create/{post.id}",
                    "type": "Create",
                    "actor": user.actor_uri(),
                    "object": to_ap_note(post),
                }
                s.commit()
                if visibility == "mention":
                    if post.mentioned_user_ids:
                        mu_users = s.query(User).filter(User.id.in_(post.mentioned_user_ids), User.is_remote == True).all()
                        for mu in mu_users:
                            if mu.inbox_url:
                                _post_to_inbox(mu.inbox_url, create_activity, user)
                else:
                    broadcast_to_followers(user, create_activity)
            except Exception as e:
                logger.warning("Failed to broadcast episode federation: %s", e)
                s.commit()
        else:
            s.commit()

        # Notify series followers
        followers = s.query(SeriesFollow).filter_by(novel_id=novel.id).all()
        for sf in followers:
            if sf.user_id != user.id:
                n = Notification(
                    user_id=sf.user_id,
                    from_user_id=user.id,
                    notification_type="new_episode",
                    metadata_json=json.dumps({
                        "novel_id": novel.id,
                        "novel_title": novel.title,
                        "episode_id": episode.id,
                        "episode_number": next_num,
                        "episode_title": title,
                    }, ensure_ascii=False),
                )
                s.add(n)
        if followers:
            s.commit()
            for sf in followers:
                if sf.user_id != user.id:
                    send_push_to_user(sf.user_id, "new_episode", user.username, metadata={"novel_id": novel.id})
                    broadcast_notif_sound(sf.user_id)

        eid = episode.id
    return {"ok": True, "episode_id": eid}


@router.get("/series/{novel_id}/episodes/{episode_id}")
def api_get_episode(request: Request, novel_id: int, episode_id: int):
    user = get_current_user(request)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        novel = episode.novel
        if novel.visibility == "private" and (not user or novel.author_id != user.id):
            raise HTTPException(status_code=404, detail="Episode not found")
        if not user and novel.visibility in ("public", "unlisted"):
            pass
        is_mine = novel.author_id == user.id if user else False
        prev_ep = s.query(Episode).filter(
            Episode.novel_id == novel_id,
            Episode.episode_number < episode.episode_number,
        )
        if not is_mine:
            prev_ep = prev_ep.filter(Episode.is_published == True)
        prev_ep = prev_ep.order_by(desc(Episode.episode_number)).first()
        next_ep = s.query(Episode).filter(
            Episode.novel_id == novel_id,
            Episode.episode_number > episode.episode_number,
        )
        if not is_mine:
            next_ep = next_ep.filter(Episode.is_published == True)
        next_ep = next_ep.order_by(Episode.episode_number).first()
        if user and not is_mine:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            existing_view = s.query(EpisodeView).filter(
                EpisodeView.user_id == user.id,
                EpisodeView.episode_id == episode.id,
                EpisodeView.viewed_at >= today_start,
            ).first()
            if not existing_view:
                episode.views = (episode.views or 0) + 1
                s.add(EpisodeView(user_id=user.id, episode_id=episode.id))
        s.commit()
        ep_json = _episode_json(episode)
        if not is_mine:
            ep_json.pop("views", None)
        result = {
            "episode": ep_json,
            "novel": _novel_json(novel, s),
            "is_mine": is_mine,
            "prev_episode": _episode_json(prev_ep) if prev_ep else None,
            "next_episode": _episode_json(next_ep) if next_ep else None,
        }
    return result


@router.post("/series/{novel_id}/episodes/{episode_id}/edit")
def api_edit_episode(request: Request, novel_id: int, episode_id: int,
                     title: str = Form(...), content: str = Form(...),
                     summary: str = Form(""), comment: str = Form(""),
                     is_published: bool = Form(True), announce: bool = Form(False),
                     visibility: str = Form("public"), announce_comment: str = Form("")):
    user = require_active_auth(request)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode or episode.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Episode not found")
        episode.title = title
        episode.content = content
        episode.summary = summary
        episode.comment = comment
        episode.is_published = is_published

        if announce:
            parts = []
            if announce_comment:
                parts.append(announce_comment)
            link = f'📖 <a href="/series/{novel_id}/episodes/{episode_id}">[{episode.novel.title}] {episode.episode_number}화: {title}</a>'
            parts.append(link)
            if summary:
                parts.append(summary)
            post_content = "\n\n".join(parts)
            ep_post_number = secrets.token_hex(4)
            post = Post(
                author_id=user.id,
                content=post_content,
                visibility=visibility,
                number=ep_post_number,
                novel_id=novel_id,
                episode_id=episode_id,
                ap_id="",
            )
            s.add(post)
            s.flush()
            post.ap_id = f"{BASE_URL}/@{user.username}/{ep_post_number}"
            s.flush()
            try:
                s.refresh(post)
                create_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/create/{post.id}",
                    "type": "Create",
                    "actor": user.actor_uri(),
                    "object": to_ap_note(post),
                }
                s.commit()
                broadcast_to_followers(user, create_activity)
            except Exception as e:
                logger.warning("Failed to broadcast episode edit federation: %s", e)
                s.commit()

        s.commit()
    return {"ok": True}


@router.post("/series/{novel_id}/episodes/{episode_id}/delete")
def api_delete_episode(request: Request, novel_id: int, episode_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        if episode.novel.author_id != user.id and user.role not in ("admin", "moderator", "owner"):
            raise HTTPException(status_code=404, detail="Episode not found")
        # Log admin action
        if episode.novel.author_id != user.id:
            log_admin_action(user.id, user.username, "delete_episode", target_type="episode", target_id=episode_id, target_username=episode.novel.author.username if episode.novel else "", details=episode.title, ip_address=request.client.host if request.client else "")
        for p in s.query(Post).filter(Post.episode_id == episode_id).all():
            p.episode_id = None
        s.flush()
        s.delete(episode)
        s.commit()
    return {"ok": True}


@router.post("/series/{novel_id}/delete")
def api_delete_novel(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        s.query(Post).filter(Post.novel_id == novel.id).update({Post.novel_id: None})
        s.query(Episode).filter(Episode.novel_id == novel.id).update({Episode.novel_id: None})
        s.delete(novel)
        s.commit()
    return {"ok": True}


def _episode_json(e, summary_only=False):
    d = {
        "id": e.id,
        "novel_id": e.novel_id,
        "episode_number": e.episode_number,
        "title": e.title,
        "summary": e.summary or "",
        "comment": e.comment or "",
        "views": e.views or 0,
        "is_published": e.is_published,
        "created_at": _fmt_dt(e.created_at),
        "updated_at": _fmt_dt(e.updated_at),
    }
    if not summary_only:
        d["content"] = e.content
    return d


def _notice_json(n):
    return {
        "id": n.id,
        "uuid": n.uuid,
        "novel_id": n.novel_id,
        "title": n.title,
        "content": n.content,
        "is_pinned": n.is_pinned,
        "created_at": _fmt_dt(n.created_at),
        "updated_at": _fmt_dt(n.updated_at),
    }


@router.get("/series/{novel_id}/drafts")
def api_list_drafts(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        drafts = s.query(EpisodeDraft).filter_by(user_id=user.id, novel_id=novel_id).order_by(desc(EpisodeDraft.updated_at)).limit(5).all()
        return {"drafts": [{"id": d.id, "title": d.title or "", "summary": d.summary or "", "content": d.content or "", "comment": d.comment or "", "is_published": d.is_published, "announce": d.announce, "announce_comment": d.announce_comment or "", "visibility": d.visibility or "public", "episode_id": d.episode_id, "created_at": _fmt_dt(d.created_at), "updated_at": _fmt_dt(d.updated_at)} for d in drafts]}


@router.post("/series/{novel_id}/drafts")
def api_save_draft(request: Request, novel_id: int, title: str = Form(""), summary: str = Form(""), content: str = Form(""), comment: str = Form(""), is_published: bool = Form(True), announce: bool = Form(False), announce_comment: str = Form(""), visibility: str = Form("public"), draft_id: int = Form(0), episode_id: int = Form(0)):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if draft_id:
            draft = s.query(EpisodeDraft).filter_by(id=draft_id, user_id=user.id, novel_id=novel_id).first()
            if not draft:
                raise HTTPException(status_code=404, detail="Draft not found")
        else:
            count = s.query(EpisodeDraft).filter_by(user_id=user.id, novel_id=novel_id).count()
            if count >= 5:
                oldest = s.query(EpisodeDraft).filter_by(user_id=user.id, novel_id=novel_id).order_by(EpisodeDraft.updated_at.asc()).first()
                if oldest:
                    s.delete(oldest)
                    s.flush()
            draft = EpisodeDraft(user_id=user.id, novel_id=novel_id)
            s.add(draft)
            s.flush()
            draft_id = draft.id
        draft.title = title
        draft.summary = summary
        draft.content = content
        draft.comment = comment
        draft.is_published = is_published
        draft.announce = announce
        draft.announce_comment = announce_comment
        draft.visibility = visibility
        draft.episode_id = episode_id or None
        draft.updated_at = func.now()
        s.commit()
        return {"ok": True, "draft_id": draft_id}


@router.post("/series/{novel_id}/drafts/{draft_id}/delete")
def api_delete_draft(request: Request, novel_id: int, draft_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        draft = s.query(EpisodeDraft).filter_by(id=draft_id, user_id=user.id, novel_id=novel_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        s.delete(draft)
        s.commit()
        return {"ok": True}


@router.get("/series/{novel_id}/notices")
def api_list_notices(request: Request, novel_id: int):
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Series not found")
        notices = s.query(SeriesNotice).filter_by(novel_id=novel_id).order_by(
            SeriesNotice.is_pinned.desc(), SeriesNotice.created_at.desc()).all()
        return [_notice_json(n) for n in notices]


@router.post("/series/{novel_id}/notices/new")
def api_create_notice(request: Request, novel_id: int, title: str = Form(...), content: str = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel or novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Series not found")
        notice = SeriesNotice(novel_id=novel_id, title=title, content=content)
        s.add(notice)
        s.commit()
        return _notice_json(notice)


@router.post("/series/{novel_id}/notices/{notice_id}/edit")
def api_edit_notice(request: Request, novel_id: int, notice_id: int, title: str = Form(...), content: str = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice or notice.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Notice not found")
        notice.title = title
        notice.content = content
        s.commit()
        return _notice_json(notice)


@router.post("/series/{novel_id}/notices/{notice_id}/delete")
def api_delete_notice(request: Request, novel_id: int, notice_id: int):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice:
            raise HTTPException(status_code=404, detail="Notice not found")
        if notice.novel.author_id != user.id and user.role not in ("admin", "moderator", "owner"):
            raise HTTPException(status_code=404, detail="Notice not found")
        s.delete(notice)
        s.commit()
    return {"ok": True}


@router.post("/series/{novel_id}/notices/{notice_id}/pin")
def api_toggle_pin_notice(request: Request, novel_id: int, notice_id: int):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice or notice.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Notice not found")
        if not notice.is_pinned:
            pinned_count = s.query(SeriesNotice).filter_by(novel_id=novel_id, is_pinned=True).count()
            if pinned_count >= 3:
                raise HTTPException(status_code=400, detail="최대 3개까지 고정할 수 있습니다")
        notice.is_pinned = not notice.is_pinned
        s.commit()
        return _notice_json(notice)


def _cleanup_avatars():
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        return
    with get_session() as s:
        used_urls = {u.profile_image for u in s.query(User).filter(User.profile_image != "").all()}
        used_urls |= {u.header_image for u in s.query(User).filter(User.header_image != "").all()}
    now = time.time()
    for path in ("avatars", "headers"):
        for key in storage.list_keys(path):
            url = storage.url(key)
            if url in used_urls:
                continue
            mtime = storage.mtime(key)
            if mtime is not None and now - mtime > 86400:
                storage.delete(key)


@router.post("/settings/update")
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


@router.post("/settings/change-email")
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


@router.post("/settings/send-verification-email")
def api_settings_send_verification(request: Request):
    user = require_auth(request)
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        if db.email_verified:
            return {"ok": True, "already_verified": True}
        _send_verification_email(db)
        s.commit()
    return {"ok": True, "email_sent": True}


MAX_VIDEO_SIZE = 26214400

@router.post("/media/upload")
def api_upload_media(request: Request, file: UploadFile = File(...)):
    user = require_active_auth(request)
    storage = get_storage()
    ext, is_image, is_video = _validate_upload(file, allow_video=True, max_size=MAX_IMAGE_SIZE, label="미디어")
    name = f"{uuid4().hex}.webp" if is_image else f"{uuid4().hex}{ext}"
    key = f"media/{name}"
    if is_image:
        img = Image.open(io.BytesIO(file.file.read()))
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=85, lossless=(img.mode == "RGBA"))
        storage.save(key, buf.getvalue())
        url = storage.url(key)
    else:
        storage.save(key, file.file.read())
        url = storage.url(key)
    return {"url": url, "type": "image" if is_image else "video"}


@router.post("/settings/change-password")
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


@router.post("/settings/migrate")
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

        # Notify target user for approval
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


@router.post("/settings/migrate/approve")
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


@router.post("/settings/migrate/reject")
def api_reject_migrate(request: Request, notification_id: int = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        n = s.query(Notification).filter_by(id=notification_id, user_id=user.id).first()
        if n:
            s.delete(n)
            s.commit()
    return {"ok": True}


@router.post("/settings/aliases")
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


@router.get("/settings/aliases")
def api_get_aliases(request: Request):
    user = require_auth(request)
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        return {"aliases": (db.aliases or []) if hasattr(db, 'aliases') else []}


@router.post("/settings/reactivate")
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


@router.post("/settings/delete-account")
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

        # Broadcast Delete to all related remote servers BEFORE deleting data
        _actor_uri = db.actor_uri()
        # Collect all remote user IDs that have interacted with this user
        _interacted = set()
        # followers + following
        for f in s.query(Follow).filter_by(following_id=db.id, accepted=True).all():
            _interacted.add(f.follower_id)
        for f in s.query(Follow).filter_by(follower_id=db.id, accepted=True).all():
            _interacted.add(f.following_id)
        # users who boosted or liked this user's posts
        _my_post_ids = [p.id for p in s.query(Post.id).filter_by(author_id=db.id).all()]
        if _my_post_ids:
            for b in s.query(Boost.user_id).filter(Boost.post_id.in_(_my_post_ids)).all():
                _interacted.add(b.user_id)
            for l in s.query(Like.user_id).filter(Like.post_id.in_(_my_post_ids)).all():
                _interacted.add(l.user_id)
            # users who replied to this user's posts
            for r in s.query(Post.author_id).filter(Post.in_reply_to_id.in_(_my_post_ids)).all():
                _interacted.add(r.author_id)
        # Deduplicate by shared_inbox_url (only remote users)
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

        # Delete posts: hard-delete if no replies, shell+delete activity if in thread
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

        # Delete all series and episodes
        for n in s.query(Novel).filter_by(author_id=db.id).all():
            for e in s.query(Episode).filter_by(novel_id=n.id).all():
                s.query(EpisodeView).filter(EpisodeView.episode_id == e.id).delete()
                s.delete(e)
            s.query(SeriesFollow).filter(SeriesFollow.novel_id == n.id).delete()
            s.query(SeriesNotice).filter(SeriesNotice.novel_id == n.id).delete()
            s.query(SeriesMute).filter(SeriesMute.novel_id == n.id).delete()
            s.delete(n)

        # Remove follow relationships
        s.query(Follow).filter(
            or_(Follow.follower_id == db.id, Follow.following_id == db.id)
        ).delete()

        # Clean up user data
        s.query(Notification).filter(
            or_(Notification.user_id == db.id, Notification.from_user_id == db.id)
        ).delete()
        s.query(PushSubscription).filter_by(user_id=db.id).delete()

        # Anonymize user data
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


@router.get("/settings/export/{export_type}")
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


@router.get("/settings/export-data")
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


@router.get("/settings/export-archive")
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


@router.post("/settings/import-data")
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


@router.post("/settings/archive-request")
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


def _save_profile_image(user_id: int, file: UploadFile, prefix: str, max_size: tuple[int, int], storage) -> str:
    _validate_upload(file, allow_video=False, max_size=MAX_AVATAR_SIZE, label="프로필 이미지")
    key = f"{prefix}/local/u{user_id}_{uuid4().hex[:8]}.webp"
    img = Image.open(file.file)
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))

        bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = bg
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=100)
    return storage.save(key, out.getvalue(), "image/webp")


@router.post("/profile/update")
def api_update_profile(request: Request, display_name: str = Form(""), summary: str = Form(""),
                       image: UploadFile = File(None), header_image: UploadFile = File(None),
                       custom_fields: str = Form("[]"), profile_hashtags: str = Form("[]"),
                       remove_avatar: bool = Form(False), remove_header: bool = Form(False)):
    user = require_active_auth(request)
    storage = get_storage()
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        db.display_name = display_name
        db.summary = summary
        if remove_avatar:
            old = db.profile_image
            db.profile_image = ""
            s.flush()
            if old:
                storage.delete(old)
        elif image and image.filename:
            new_url = _save_profile_image(user.id, image, "avatars", (400, 400), storage)
            old = db.profile_image
            db.profile_image = new_url
            s.flush()
            if old:
                storage.delete(old)
        if remove_header:
            old = db.header_image
            db.header_image = ""
            s.flush()
            if old:
                storage.delete(old)
        elif header_image and header_image.filename:
            new_url = _save_profile_image(user.id, header_image, "headers", (1500, 500), storage)
            old = db.header_image
            db.header_image = new_url
            s.flush()
            if old:
                storage.delete(old)
        try:
            parsed_fields = json.loads(custom_fields)
            if isinstance(parsed_fields, list):
                db.custom_fields = [
                    {"name": f.get("name") or f.get("label", ""), "value": f.get("value", "")}
                    for f in parsed_fields
                ]
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            parsed_tags = json.loads(profile_hashtags)
            if isinstance(parsed_tags, list):
                db.profile_hashtags = parsed_tags
        except (json.JSONDecodeError, TypeError):
            pass
        s.commit()
    _cleanup_avatars()
    threading.Thread(target=_broadcast_update_actor, args=(user,), daemon=True).start()
    return {"ok": True}


@router.get("/explore")
def api_explore(request: Request, limit: int = Query(20), offset: int = Query(0)):
    user = get_current_user(request)
    with get_session() as s:
        # 1. 포스트 메인 쿼리
        local_ids = s.query(User.id).filter_by(is_remote=False).subquery()
        posts = s.query(Post).options(
            selectinload(Post.author)
        ).filter(
            Post.author_id.in_(local_ids),
            Post.visibility == "public",
            Post.is_deleted == False,
            Post.in_reply_to_id == None,
            Post.author.has(User.is_suspended == False),
        ).order_by(
            desc(Post.created_at)
        ).offset(offset).limit(limit + 1).all()
        has_more = len(posts) > limit
        posts = posts[:limit]

        # 2. 사용자 활동(좋아요, 부스트, 북마크, 리액션, 부스터) 배치 로딩
        post_ids = [p.id for p in posts]
        _liked_ids = _boosted_ids = _bookmarked_ids = set()
        _my_reaction_map = {}
        _reactions_map = {}
        _booster_map = {}
        _mentioned_users_map = {}
        _boost_originals = {}
        if post_ids:
            boost_pointer_ids = {p.boost_of_id for p in posts if p.boost_of_id}
            if boost_pointer_ids:
                for orig in s.query(Post).options(selectinload(Post.author)).filter(Post.id.in_(boost_pointer_ids), Post.is_deleted == False).all():
                    _boost_originals[orig.id] = orig
        if user and post_ids:
            _liked_ids = {l.post_id for l in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(post_ids)).all()}
            _boosted_ids = {b.post_id for b in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(post_ids)).all()}
            for l in s.query(Like.post_id, Like.reaction).filter(Like.user_id == user.id, Like.post_id.in_(post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[l.post_id] = l.reaction
            for bid, buid in s.query(Boost.post_id, Boost.user_id).filter(Boost.post_id.in_(post_ids)).order_by(desc(Boost.created_at)).all():
                if bid not in _booster_map:
                    _booster_map[bid] = buid
            if _booster_map:
                _booster_users = {u.id: u for u in s.query(User).filter(User.id.in_(set(_booster_map.values()))).all()}
                _booster_map = {pid: _booster_users.get(uid) for pid, uid in _booster_map.items()}
            for pid, react, cnt in s.query(Like.post_id, func.coalesce(Like.reaction, "★"), func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all():
                if pid not in _reactions_map:
                    _reactions_map[pid] = {}
                _reactions_map[pid][react] = cnt
            all_mentioned_ids = set()
            for p in posts:
                if p.mentioned_user_ids:
                    all_mentioned_ids.update(p.mentioned_user_ids)
            if all_mentioned_ids:
                _mentioned_users = {}
                for _um in s.query(User).filter(User.id.in_(all_mentioned_ids)).all():
                    if _um.is_remote and _um.remote_url:
                        _name = _um.username.split("@")[0]
                        _domain = urlparse(_um.remote_url).hostname or ""
                        _mentioned_users[_um.id] = f"{_name}@{_domain}"
                    else:
                        _mentioned_users[_um.id] = _um.username
                for p in posts:
                    if p.mentioned_user_ids:
                        _mentioned_users_map[p.id] = [_mentioned_users.get(mid, "?") for mid in p.mentioned_user_ids if mid in _mentioned_users]
                    else:
                        _mentioned_users_map[p.id] = []

        # 3. 첫 페이지에서만 소설 목록 조회
        novels = []
        _followers_map = {}
        if offset == 0:
            novels = _apply_latest_activity_order(s.query(Novel).options(
                selectinload(Novel.author),
                selectinload(Novel.tag_list),
            ).filter(
                Novel.visibility == "public",
                Novel.is_published == True,
            ), s).limit(20).all()
            if novels:
                novel_ids = [n.id for n in novels]
                for nid, cnt in s.query(SeriesFollow.novel_id, func.count(SeriesFollow.id)).filter(SeriesFollow.novel_id.in_(novel_ids)).group_by(SeriesFollow.novel_id).all():
                    _followers_map[nid] = cnt

        return {
            "posts": [_post_json(p, s, user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids, _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map, _booster_map=_booster_map, _mentioned_users_map=_mentioned_users_map, _boost_originals=_boost_originals, _skip_emojis=True) for p in posts],
            "has_more": has_more,
            "novels": [_novel_json(n, s, _followers_map=_followers_map) for n in novels],
        }


@router.get("/search")
def api_search(request: Request, q: str = Query(""), author: str = Query("")):
    user = get_current_user(request)
    query = q.strip().lstrip("@").lstrip("#")
    if not query:
        return {"posts": [], "novels": [], "users": []}
    # Check if the query contains a blocked/allowed domain (handles only, not URLs)
    blocked_domain = None
    if not query.startswith("http") and "@" in query and "." in query:
        parts = query.split("@")
        if len(parts) == 2 and parts[1]:
            domain = parts[1].strip().lower()
            if domain:
                with get_session() as s_check:
                    mode = ServerSetting.get(s_check).federation_mode or "blacklist"
                    if mode == "whitelist":
                        allowed = s_check.query(AllowedServer).filter_by(domain=domain).first()
                        if not allowed:
                            blocked_domain = domain
                    else:
                        blocked = s_check.query(FederationBlock).filter_by(domain=domain).first()
                        if blocked:
                            blocked_domain = domain
    with get_session() as s:
        pattern = f"%{query}%"
        is_hashtag_search = q.strip().startswith("#")
        following_ids = []
        if user:
            following_ids = [f.following_id for f in s.query(Follow).filter_by(follower_id=user.id, accepted=True).all()]
        if is_hashtag_search:
            tag = s.query(Tag).filter_by(name=query.lower()).first()
            if tag:
                # 1. 포스트 쿼리
                q_posts = s.query(Post).options(selectinload(Post.author)).filter(
                    Post.tag_list.any(name=tag.name),
                    Post.is_deleted == False,
                    Post.author.has(User.is_suspended == False),
                )
                if user:
                    q_posts = q_posts.filter(
                        Post.visibility == "public"
                        | (Post.author_id.in_(following_ids) & Post.visibility.in_(["public", "home", "followers"]))
                        | (Post.author_id == user.id)
                        | Post.mentioned_user_ids.contains([user.id])
                    )
                else:
                    q_posts = q_posts.filter(Post.visibility == "public")
                if author:
                    author_user = s.query(User).filter_by(username=author).first()
                    if author_user:
                        q_posts = q_posts.filter(Post.author_id == author_user.id)
                posts = q_posts.order_by(desc(Post.created_at)).limit(60).all()
                if user:
                    posts = _timeline_filter(posts, s, user, "federated", following_ids)[:20]
                else:
                    posts = posts[:20]
            else:
                # 태그가 디비에 없으면 둘 다 깔끔하게 빈 리스트 처리
                posts = []
            if tag:
                # 2. 소설(Novel) 쿼리 💡 (오류 방지를 위해 tag가 확실히 있을 때만 돌도록 안으로 이동)
                novels = s.query(Novel).options(selectinload(Novel.author)).filter(
                    Novel.tag_list.any(name=tag.name),
                    Novel.is_published == True,
                    Novel.visibility != "private",
                ).order_by(desc(Novel.updated_at)).limit(20).all()
            else:
                # 태그가 디비에 없으면 둘 다 깔끔하게 빈 리스트 처리
                novels = []
        else:
            q_posts = s.query(Post).options(selectinload(Post.author)).filter(
                Post.content.ilike(pattern),
                Post.is_deleted == False,
                Post.author.has(User.is_suspended == False),
            )
            if user:
                q_posts = q_posts.filter(
                    Post.visibility == "public"
                    | (Post.author_id.in_(following_ids) & Post.visibility.in_(["public", "home", "followers"]))
                    | (Post.author_id == user.id)
                    | Post.mentioned_user_ids.contains([user.id])
                )
            else:
                q_posts = q_posts.filter(Post.visibility == "public")
            posts = q_posts.order_by(desc(Post.created_at)).limit(60).all()
            if user:
                posts = _timeline_filter(posts, s, user, "federated", following_ids)[:20]
            else:
                posts = posts[:20]
            novels = _apply_latest_activity_order(s.query(Novel).options(selectinload(Novel.author)).filter(
                or_(Novel.title.ilike(pattern), Novel.description.ilike(pattern)),
                Novel.is_published == True,
                Novel.visibility == "public",
            ), s).limit(20).all()
        local_users = s.query(User).filter(
            User.is_remote == False,
            User.is_suspended == False,
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern)),
        ).limit(20).all()
        remote_users = s.query(User).filter(
            User.is_remote == True,
            User.is_suspended == False,
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern)),
        ).limit(10).all()
        all_users = list(local_users) + list(remote_users)
        # If query is handle@domain and no remote match yet, try to resolve
        if "@" in query and not blocked_domain:
            at_parts = query.split("@", 1)
            if len(at_parts) == 2 and at_parts[0] and at_parts[1]:
                r_handle, r_domain = at_parts[0].strip().lower(), at_parts[1].strip().lower()
                already_found = any(
                    u.is_remote and u.username.lower().startswith(f"{r_handle}@") and u.username.lower().endswith(f"@{r_domain}")
                    for u in all_users
                )
                if not already_found:
                    try:
                        urls = [
                            f"https://{r_domain}/users/{r_handle}",
                            f"https://{r_domain}/@{r_handle}",
                            f"https://{r_domain}/u/{r_handle}",
                            f"https://{r_domain}/profile/{r_handle}",
                        ]
                        resolved = None
                        for url in urls:
                            try:
                                resolved = _resolve_actor(url)
                                if resolved:
                                    break
                            except Exception:
                                continue
                        if not resolved:
                            wf = httpx.get(
                                f"https://{r_domain}/.well-known/webfinger?resource=acct:{r_handle}@{r_domain}",
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
                        if resolved:
                            refreshed = s.query(User).get(resolved.id)
                            if refreshed:
                                all_users.append(refreshed)
                    except Exception:
                        pass
        result = {
            "posts": [_post_json(p, s, user) for p in posts],
            "novels": [_novel_json(n, s) for n in novels],
            "users": [_user_json(u) for u in all_users],
        }
        if blocked_domain:
            result["blocked_domain"] = blocked_domain
        return result


def _fetch_and_save_ap_object(obj, user, _visited=None, _depth=0):
    """Fetch a remote AP object, resolve its author, save to DB, return post.
    Also recursively fetches parent posts (thread ancestors) up to depth 5."""
    if _depth > 5:
        return None
    if _visited is None:
        _visited = set()

    # 1. 스레드 상위 글 역추적 로직 안전하게 실행
    in_reply_to = obj.get("inReplyTo", "")
    if isinstance(in_reply_to, dict):
        in_reply_to = in_reply_to.get("id", "")
    if in_reply_to and in_reply_to not in _visited:
        _visited.add(in_reply_to)
        parent_data = _ap_fetch(in_reply_to, user)
        if parent_data:
            parent_obj = parent_data.get("object", parent_data)
            # 💡 재귀 함수가 안전하게 마칠 수 있도록 단독 실행 확보
            try:
                _fetch_and_save_ap_object(parent_obj, user, _visited, _depth + 1)
            except Exception as e:
                print(f"[WARN] Failed to process parent post {in_reply_to}: {e}", flush=True)

    actor_url = obj.get("id")
    post = None
    # 2. 본문 페치 및 DB 저장 로직 수행
    with get_session() as session:
        try:
            post = _fetch_remote_post(actor_url, user, session, _depth)
            # 💡 페치가 성공했을 때만 확실하게 DB 세션 커밋을 보장
            if post:
                session.commit()
        except Exception as e:
            # 💡 단순 print 대신 에러가 발생한 정확한 라인과 원인을 추적하기 위해 traceback 추가
            print(f"[ERROR] Failed to fetch remote post from {actor_url}: {e}", flush=True)
            traceback.print_exc() 
            return None # 껍데기를 만들지 않도록 에러 시 None 리턴 구조로 방어

        if not post:
            return None
        return _post_json(post, session, user)


def _safe_httpx_get(url, headers=None, timeout=15, max_size=5*1024*1024):
    """HTTP GET with redirect validation and size limit."""
    if not _validate_url(url):
        print(f"[SAFE_GET] blocked by _validate_url url={url}", flush=True)
        return None
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    # Intercept redirects to validate each target
    original_send = client.send
    def _validated_send(request, **kwargs):
        if _validate_url(str(request.url)):
            return original_send(request, **kwargs)
        raise httpx.InvalidURL(f"Blocked redirect to {request.url}")
    client.send = _validated_send
    try:
        resp = client.get(url, headers=headers)
        client.close()
        print(f"[SAFE_GET] url={url} status={resp.status_code} len={len(resp.content)}", flush=True)
        if resp.status_code != 200:
            return None
        if len(resp.content) > max_size:
            return None
        return resp
    except Exception:
        client.close()
        return None

def _ap_fetch(url, user):
    """Fetch a remote URL with HTTP Signature, return parsed JSON."""
    # Convert web URL /@username/id to AP URL /users/username/statuses/id
    original_url = url
    m = re.match(r'^(https?://[^/]+)/@(\w+(?:@\S+)?)/([\w-]+)(\?.*)?$', url)
    if m:
        base, username, status_id, query = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        url = f"{base}/users/{username}/statuses/{status_id}{query}"

    if not _validate_url(url):
        return None

    def _sign_and_fetch(target_url, _depth=0):
        if _depth > 2:
            return None
        date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        parsed = urlparse(target_url)
        path_with_query = parsed.path or "/"
        if parsed.query:
            path_with_query += f"?{parsed.query}"
        signed_string = (
            f"(request-target): get {path_with_query}\n"
            f"host: {parsed.netloc}\n"
            f"date: {date_str}"
        )
        try:
            signature = sign_string(signed_string, get_private_key(user, SECRET_KEY))
        except Exception:
            return None
        signature_header = (
            f'keyId="{user.actor_uri()}#main-key",'
            f'headers="(request-target) host date",'
            f'signature="{signature}"'
        )
        headers = {
            "Accept": "application/activity+json",
            "Signature": signature_header,
            "Date": date_str,
            "Host": parsed.netloc,
        }
        resp = _safe_httpx_get(target_url, headers=headers)
        if not resp or resp.status_code != 200:
            print(f"[AP_FETCH] url={target_url} status={resp.status_code if resp else 'None resp'}", flush=True)
            return None
        ct = resp.headers.get("content-type", "")
        if "json" not in ct and "activity" not in ct:
            html = resp.text[:100000]
            alt_m = re.search(r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/activity\+json["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
            if not alt_m:
                alt_m = re.search(r'<link[^>]+type=["\']application/activity\+json["\'][^>]+rel=["\']alternate["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
            if not alt_m:
                alt_m = re.search(r'href=["\']([^"\']+)["\'][^>]*type=["\']application/activity\+json["\']', html, re.I)
            if alt_m:
                alt_url = alt_m.group(1)
                print(f"[AP_FETCH] HTML response, found alternate AP URL: {alt_url}", flush=True)
                return _sign_and_fetch(alt_url, _depth + 1)
            print(f"[AP_FETCH] HTML response, no alternate link found for {target_url}", flush=True)
            return None
        try:
            return resp.json()
        except Exception as e:
            print(f"[AP_FETCH] json error url={target_url}: {e}", flush=True)
            return None

    result = _sign_and_fetch(url)
    # Fallback: try original /@username/id URL if /users/.../statuses/... returned 404
    if not result and original_url != url:
        print(f"[AP_FETCH] fallback to original_url={original_url}", flush=True)
        result = _sign_and_fetch(original_url)
    print(f"[AP_FETCH] result_is_none={result is None} original={original_url} converted={url}", flush=True)
    return result

_unread_cache: dict[int, tuple[int, float]] = {}
_UNREAD_CACHE_TTL = 5.0

@router.get("/notifications/unread-count")
def api_unread_count(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    now = time.time()
    cached = _unread_cache.get(user.id)
    if cached and now - cached[1] < _UNREAD_CACHE_TTL:
        return {"count": cached[0]}
    with get_session() as s:
        count = s.query(Notification.id).filter_by(user_id=user.id, is_read=False).count()
    _unread_cache[user.id] = (count, now)
    return {"count": count}


def _check_fetch_domain_allowed(url: str) -> str | None:
    """Return an error message if the URL's domain is federated-blocked, else None."""
    domain = urlparse(url).hostname or ""
    if domain:
        with get_session() as s:
            mode = ServerSetting.get(s).federation_mode or "blacklist"
            if mode == "whitelist":
                allowed = s.query(AllowedServer).filter_by(domain=domain).first()
                if not allowed:
                    return f"허용되지 않은 서버입니다: {domain}"
            else:
                blocked = s.query(FederationBlock).filter_by(domain=domain).first()
                if blocked:
                    reason = f" ({blocked.reason})" if blocked.reason else ""
                    return f"차단된 서버입니다{reason}: {domain}"
    return None


def _background_fetch_outbox(url: str, user_id: int, actor_id: int):
    with get_session() as s:
        user = s.query(User).get(user_id)
        actor = s.query(User).get(actor_id)
        if not user or not actor:
            return
        try:
            outbox_url = getattr(actor, "outbox_url", None) or getattr(actor, "endpoints", {}).get("sharedInbox", "")
            if not outbox_url:
                date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                parsed = urlparse(url)
                created = int(time.time())
                ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
                priv = get_private_key(user, SECRET_KEY)
                sig = sign_string(ss, priv)
                sig_header = f'keyId="{user.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
                headers = {"Accept": "application/activity+json", "Signature": sig_header, "Date": date, "Host": parsed.netloc}
                r = _safe_httpx_get(url, headers=headers)
                if r:
                    outbox_url = r.json().get("outbox", "")
            if outbox_url:
                parsed2 = urlparse(outbox_url)
                date2 = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                created2 = int(time.time())
                path2 = parsed2.path or "/"
                if parsed2.query:
                    path2 += f"?{parsed2.query}"
                priv = get_private_key(user, SECRET_KEY)
                ss2 = f"(request-target): get {path2}\nhost: {parsed2.netloc}\ndate: {date2}\n(created): {created2}"
                sig2 = sign_string(ss2, priv)
                sig_header2 = f'keyId="{user.actor_uri()}#main-key",algorithm="hs2019",created="{created2}",headers="(request-target) host date (created)",signature="{sig2}"'
                headers2 = {"Accept": "application/activity+json", "Signature": sig_header2, "Date": date2, "Host": parsed2.netloc}
                resp = _safe_httpx_get(f"{outbox_url}?page=1", headers=headers2)
                if resp:
                    outbox_data = resp.json()
                    for item in outbox_data.get("orderedItems", []):
                        try:
                            obj = item.get("object", item)
                            _fetch_and_save_ap_object(obj, actor)
                        except Exception:
                            pass
        except Exception:
            pass


@router.post("/fetch-actor")
def api_fetch_actor(request: Request, background_tasks: BackgroundTasks, url: str = Form(...)):
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    err = _check_fetch_domain_allowed(url)
    if err:
        raise HTTPException(status_code=403, detail=err)

    # Normalize /@username to /users/username for DB lookup
    _p = urlparse(url)
    _db_url = url
    if "/@" in _p.path:
        _uname = _p.path.split("/@")[-1].strip("/")
        if _uname and "/" not in _uname:
            _db_url = f"{_p.scheme}://{_p.netloc}/users/{_uname}"

    # 로컬 DB에 이미 존재하는 유저인지 먼저 확인 (외부 네트워크 요청 회피)
    with get_session() as _s:
        local_user = _s.query(User).filter(or_(User.remote_url == url, User.remote_url == _db_url)).first()
        if local_user:
            background_tasks.add_task(_background_fetch_outbox, url, user.id, local_user.id)
            return _user_json(local_user)

    actor = _resolve_actor(url, force_refresh=False, sign_as=user)
    if not actor:
        raise HTTPException(status_code=400, detail="Cannot resolve actor")

    background_tasks.add_task(_background_fetch_outbox, url, user.id, actor.id)

    with get_session() as _s:
        _attached = _s.query(User).filter(or_(User.remote_url == url, User.remote_url == _db_url)).first()
        if not _attached:
            _attached = _s.query(User).get(actor.id)
        return _user_json(_attached)


@router.get("/emojis")
def api_list_emojis(limit: int = Query(30), offset: int = Query(0), q: str = Query(""), category: str = Query("")):
    with get_session() as s:
        query = s.query(CustomEmoji)
        if q:
            query = query.filter(
                or_(
                    CustomEmoji.keyword.ilike(f"%{q}%"),
                    CustomEmoji.category.ilike(f"%{q}%"),
                )
            )
        if category != "remote":
            query = query.filter(CustomEmoji.category != "remote")
        elif category == "remote":
            query = query.filter(CustomEmoji.category == "remote")
        total = query.count()
        emojis = query.order_by(desc(CustomEmoji.created_at)).offset(offset).limit(limit).all()
        result = [
            {
                "id": e.id,
                "keyword": e.keyword,
                "file_name": e.file_name,
                "category": e.category or "",
                "aliases": e.aliases or [],
                "url": _emoji_url(e.file_name, e.domain or "", e.category or ""),
                "source_url": e.source_url or "",
                "domain": e.domain or "",
            }
            for e in emojis
        ]
    return JSONResponse({"emojis": result, "total": total, "has_more": offset + limit < total}, headers={"Cache-Control": "no-cache, must-revalidate"})


@router.post("/emojis")
def api_create_emoji(
    request: Request,
    keyword: str = Form(...),
    category: str = Form(""),
    aliases: str = Form(""),
    image: UploadFile = File(...),
):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not keyword.strip():
        raise HTTPException(status_code=400, detail="Keyword is required")
    keyword = keyword.strip().lower().replace(" ", "_")
    if not re.match(r'^[a-z0-9_]+$', keyword):
        raise HTTPException(status_code=400, detail="Keyword must be lowercase alphanumeric with underscores")

    allowed_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if image.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {image.content_type}")

    ct_to_ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
    ext = ct_to_ext.get(image.content_type, "png")
    file_name = f"{uuid4().hex}.{ext}"
    local_dir = os.path.join(EMOJI_DIR, "local")
    os.makedirs(local_dir, exist_ok=True)
    file_path = os.path.join(local_dir, file_name)
    _emoji_data = None

    try:
        tmp = Image.open(image.file)
        w, h = tmp.size
        tmp.close()
        image.file.seek(0)
        if h > 0 and w / h > 1.5:
            raise HTTPException(status_code=400, detail="Emoji is too wide (max 2x height)")
        if ext == "gif":
            _emoji_data = image.file.read()
            with open(file_path, "wb") as f:
                f.write(_emoji_data)
        else:
            file_name = f"{uuid4().hex}.webp"
            file_path = os.path.join(local_dir, file_name)
            img = Image.open(image.file)
            if img.mode == "RGBA" or img.mode == "P":
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            if img.width > 66 or img.height > 66:
                img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=100)
            _emoji_data = buf.getvalue()
            with open(file_path, "wb") as f:
                f.write(_emoji_data)
        if S3_ENABLED and _emoji_data:
            try:
                get_storage().save(f"emojis/local/{file_name}", _emoji_data, f"image/{ext}")
            except Exception:
                pass
    except Exception as e:
        logger.exception("Failed to process emoji image")
        raise HTTPException(status_code=400, detail="Failed to process image")

    alias_list = [a.strip().lower().replace(" ", "_") for a in aliases.split(",") if a.strip()]

    with get_session() as s:
        existing = s.query(CustomEmoji).filter_by(keyword=keyword).first()
        if existing:
            os.remove(file_path)
            raise HTTPException(status_code=400, detail=f"Emoji ':${keyword}:' already exists")
        emoji = CustomEmoji(
            keyword=keyword,
            file_name=file_name,
            category=category or "",
            aliases=alias_list,
        )
        s.add(emoji)
        s.commit()
        _refresh_emoji_cache_forcibly(s)
        return {
            "id": emoji.id,
            "keyword": emoji.keyword,
            "file_name": emoji.file_name,
            "category": emoji.category or "",
            "aliases": emoji.aliases or [],
            "url": _emoji_url(emoji.file_name, emoji.domain or "", emoji.category or ""),
        }


@router.patch("/emojis/{emoji_id}")
def api_update_emoji(request: Request, emoji_id: int, category: str = Form(""), keyword: str = Form(""), aliases: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        emoji = s.query(CustomEmoji).get(emoji_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        if keyword:
            keyword_clean = keyword.strip().lower().replace(" ", "_").replace(":", "")
            if keyword_clean != emoji.keyword:
                existing = s.query(CustomEmoji).filter(CustomEmoji.keyword == keyword_clean, CustomEmoji.id != emoji_id).first()
                if existing:
                    raise HTTPException(status_code=400, detail="Keyword already taken")
                emoji.keyword = keyword_clean
        if category:
            emoji.category = category
        emoji.aliases = [a.strip().lower().replace(" ", "_") for a in aliases.split(",") if a.strip()]
        s.commit()
        _refresh_emoji_cache_forcibly(s)
        return {"ok": True, "emoji": {"id": emoji.id, "keyword": emoji.keyword, "file_name": emoji.file_name, "category": emoji.category, "aliases": emoji.aliases or [], "url": _emoji_url(emoji.file_name, emoji.domain or "", emoji.category or ""), "source_url": emoji.source_url or "", "domain": emoji.domain or ""}}


@router.post("/emojis/{emoji_id}/copy")
def api_copy_emoji(request: Request, emoji_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        src = s.query(CustomEmoji).get(emoji_id)
        if not src:
            raise HTTPException(status_code=404, detail="Emoji not found")
        new_kw = src.keyword
        existing = s.query(CustomEmoji).filter_by(keyword=new_kw, category="기본").first()
        if existing:
            raise HTTPException(status_code=400, detail="Local emoji with this keyword already exists")
        _ext = src.file_name.rsplit(".", 1)[-1] if "." in src.file_name else "webp"
        _new_fname = f"{new_kw}.{_ext}"
        _src_sub = "remote" if src.domain or src.category == "remote" else "local"
        _data = None

        _storage = get_storage()
        try:
            _data = _storage.get(f"emojis/{_src_sub}/{src.file_name}")
        except Exception:
            pass
        if not _data:
            _src_path = os.path.join(EMOJI_DIR, _src_sub, src.file_name)
            if os.path.isfile(_src_path):
                with open(_src_path, "rb") as f:
                    _data = f.read()

        if _data:
            _dst_local = os.path.join(EMOJI_DIR, "local", _new_fname)
            os.makedirs(os.path.dirname(_dst_local), exist_ok=True)
            with open(_dst_local, "wb") as f:
                f.write(_data)
            try:
                _storage.save(f"emojis/local/{_new_fname}", _data, f"image/{_ext}")
            except Exception:
                pass

        copy = CustomEmoji(keyword=new_kw, file_name=_new_fname, category="기본", aliases=src.aliases or [])
        s.add(copy)
        s.commit()
        _refresh_emoji_cache_forcibly(s)
        return {"ok": True, "emoji": {"id": copy.id, "keyword": copy.keyword, "file_name": copy.file_name, "category": copy.category, "aliases": copy.aliases or [], "url": _emoji_url(copy.file_name, "", copy.category or ""), "source_url": copy.source_url or "", "domain": copy.domain or ""}}


@router.delete("/emojis/{emoji_id}")
def api_delete_emoji(request: Request, emoji_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        emoji = s.query(CustomEmoji).get(emoji_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        _del_sub = "remote" if emoji.domain or emoji.category == "remote" else "local"
        try:
            get_storage().delete(f"emojis/{_del_sub}/{emoji.file_name}")
        except Exception:
            pass
        file_path = os.path.join(EMOJI_DIR, _del_sub, emoji.file_name)
        if os.path.isfile(file_path):
            os.remove(file_path)
        s.delete(emoji)
        s.commit()
        _refresh_emoji_cache_forcibly(s)
    return {"ok": True}


# Admin endpoints moved to app/routes.api._admin


# ── User mute/block ──
@router.get("/mutes/users")
def api_list_user_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(UserMute).filter_by(user_id=user.id).order_by(UserMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "target_user_id": m.target_user_id, "username": m.target_user.username, "display_name": m.target_user.display_name, "avatar": m.target_user.profile_image or "", "duration": m.duration, "hide_notifications": m.hide_notifications, "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@router.post("/mutes/users/{target_user_id}")
def api_mute_user(request: Request, target_user_id: int, duration: int = Form(0), hide_notifications: bool = Form(False)):
    user = require_active_auth(request)
    if user.id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot mute yourself")
    with get_session() as s:
        existing = s.query(UserMute).filter_by(user_id=user.id, target_user_id=target_user_id).first()
        if existing:
            existing.duration = duration
            existing.hide_notifications = hide_notifications
            s.commit()
            return {"ok": True}
        s.add(UserMute(user_id=user.id, target_user_id=target_user_id, duration=duration, hide_notifications=hide_notifications))
        s.commit()
    return {"ok": True}


@router.delete("/mutes/users/{target_user_id}")
def api_unmute_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(UserMute).filter_by(user_id=user.id, target_user_id=target_user_id).delete()
        s.commit()
    return {"ok": True}


@router.get("/blocks/users")
def api_list_user_blocks(request: Request):
    user = require_auth(request)
    with get_session() as s:
        blocks = s.query(UserBlock).filter_by(user_id=user.id).order_by(UserBlock.created_at.desc()).all()
        return {"blocks": [{"id": b.id, "target_user_id": b.target_user_id, "username": b.target_user.username, "display_name": b.target_user.display_name, "avatar": b.target_user.profile_image or "", "created_at": _fmt_dt(b.created_at)} for b in blocks]}


@router.post("/blocks/users/{target_user_id}")
def api_block_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    if user.id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    target_remote_url = None
    target_shared_inbox = None
    target_id = None
    with get_session() as s:
        existing = s.query(UserBlock).filter_by(user_id=user.id, target_user_id=target_user_id).first()
        if existing:
            return {"ok": True}
        s.add(UserBlock(user_id=user.id, target_user_id=target_user_id))
        # Remove follows both ways
        s.query(Follow).filter_by(follower_id=user.id, following_id=target_user_id).delete()
        s.query(Follow).filter_by(follower_id=target_user_id, following_id=user.id).delete()
        s.commit()
        target = s.query(User).get(target_user_id)
        if target:
            target_remote_url = target.remote_url
            target_shared_inbox = target.shared_inbox_url or target.inbox_url
            target_id = target.id
    if target_remote_url and target_shared_inbox:
        try:
            block_id = f"{BASE_URL}/users/{user.username}/status/activities/block/{target_id}"
            actor_uri = f"{BASE_URL}/users/{user.username}"
            block_activity = {
                "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
                "type": "Block",
                "id": block_id,
                "actor": actor_uri,
                "to": [target_remote_url],
                "object": target_remote_url,
            }
            _post_to_inbox(target_shared_inbox, block_activity, user)
        except Exception:
            pass
    return {"ok": True}


@router.delete("/blocks/users/{target_user_id}")
def api_unblock_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    target_remote_url = None
    target_shared_inbox = None
    target_id = None
    with get_session() as s:
        target = s.query(User).get(target_user_id)
        if target:
            target_remote_url = target.remote_url
            target_shared_inbox = target.shared_inbox_url or target.inbox_url
            target_id = target.id
        s.query(UserBlock).filter_by(user_id=user.id, target_user_id=target_user_id).delete()
        s.commit()
    if target_remote_url:
        try:
            block_id = f"{BASE_URL}/users/{user.username}/status/activities/block/{target_id}"
            actor_uri = f"{BASE_URL}/users/{user.username}"
            undo_activity = {
                "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
                "type": "Undo",
                "id": f"{BASE_URL}/users/{user.username}/status/activities/undo/{target_id}",
                "actor": actor_uri,
                "to": [target_remote_url],
                "object": {
                    "id": block_id,
                    "type": "Block",
                    "actor": actor_uri,
                    "object": target_remote_url,
                },
            }
            _post_to_inbox(target_shared_inbox, undo_activity, user)
        except Exception:
            pass
    return {"ok": True}


# ── Series mute ──
@router.get("/mutes/series")
def api_list_series_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(SeriesMute).filter_by(user_id=user.id).order_by(SeriesMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "novel_id": m.novel_id, "title": m.novel.title, "cover_image": m.novel.cover_image or "", "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@router.post("/mutes/series/{novel_id}")
def api_mute_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(SeriesMute).filter_by(user_id=user.id, novel_id=novel_id).first()
        if existing:
            return {"ok": True}
        s.add(SeriesMute(user_id=user.id, novel_id=novel_id))
        s.commit()
    return {"ok": True}


@router.delete("/mutes/series/{novel_id}")
def api_unmute_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(SeriesMute).filter_by(user_id=user.id, novel_id=novel_id).delete()
        s.commit()
    return {"ok": True}


# ── Keyword mute ──
@router.get("/mutes/keywords")
def api_list_keyword_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(KeywordMute).filter_by(user_id=user.id).order_by(KeywordMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "keyword": m.keyword, "name": m.name or "", "mode": m.mode, "is_regex": m.is_regex, "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@router.post("/mutes/keywords")
def api_add_keyword_mute(request: Request, keyword: str = Form(...), mode: str = Form("or"), is_regex: bool = Form(False), name: str = Form("")):
    user = require_active_auth(request)
    kw = keyword.strip()
    if not kw:
        raise HTTPException(status_code=400, detail="Keyword cannot be empty")
    if mode not in ("and", "or"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    if is_regex:
        kw = json.dumps([kw])
    else:
        keywords = [k.strip() for k in kw.split("\n") if k.strip()]
        kw = json.dumps(keywords)
    with get_session() as s:
        existing = s.query(KeywordMute).filter_by(user_id=user.id, keyword=kw, mode=mode, is_regex=is_regex).first()
        if existing:
            return {"ok": True}
        s.add(KeywordMute(user_id=user.id, keyword=kw, name=name, mode=mode, is_regex=is_regex))
        s.commit()
    return {"ok": True}


@router.delete("/mutes/keywords/{mute_id}")
def api_remove_keyword_mute(request: Request, mute_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(KeywordMute).filter_by(id=mute_id, user_id=user.id).delete()
        s.commit()
    return {"ok": True}


def _resolve_admin_users(s, admin_ids_str: str):
    if not admin_ids_str:
        admin_ids_str = "owner"
    handles = [h.strip().lstrip("@") for h in admin_ids_str.split(",") if h.strip()]
    if not handles:
        return []
    return s.query(User).filter(User.username.in_(handles)).all()


@router.post("/link-preview")
def api_link_preview(url: str = Form(...)):
    parsed = urlparse(url)
    domain = parsed.netloc
    result = {"url": url, "title": domain, "description": "", "image": ""}
    try:
        resp = httpx.get(url, headers={"User-Agent": "WRIT/1.0"}, timeout=10, follow_redirects=True)
        if resp.status_code == 200:
            html_text = resp.text
            def _og(n):
                m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', html_text, re.I)
                if not m:
                    m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', html_text, re.I)
                return m.group(1) if m else ""
            og_title = _og("title") or re.search(r'<title>([^<]*)</title>', html_text, re.I)
            result["title"] = html.unescape((_og("title") or (og_title.group(1) if og_title else domain)))[:200]
            result["description"] = html.unescape(_og("description") or "")[:400]
            result["image"] = _og("image") or ""
            if result["image"] and result["image"].startswith("/"):
                result["image"] = f"{parsed.scheme}://{parsed.netloc}{result['image']}"
    except Exception:
        pass
    return result


@router.get("/server-info")
def api_server_info():
    with get_session() as s:
        settings = ServerSetting.get(s)
        admins = _resolve_admin_users(s, settings.admin_ids or "")
        admin_email = settings.admin_email or (admins[0].email if admins else "")
        return {
            "name": settings.server_name or "WRIT",
            "description": getattr(settings, 'server_description', '') or '',
            "admins": [
                {"username": a.username, "email": admin_email or ""}
                for a in admins
            ],
            "logo": settings.logo,
            "favicon": settings.favicon,
            "app_icon": settings.app_icon,
            "enable_reactions": bool(settings.enable_reactions),
        }


# Admin endpoints moved to app/routes.api._admin


def _read_storage_file(url: str) -> bytes:
    """Read file from storage by URL. Handles both /uploads/... and absolute URLs."""
    storage = get_storage()
    if isinstance(storage, LocalStorage):
        key = storage._extract_path(url)
        if key and os.path.isfile(key):
            with open(key, "rb") as f:
                return f.read()
    try:
        if not url.startswith("http"):
            url = f"{BASE_URL}{url}"
        resp = httpx.get(url, timeout=10)
        if resp.is_success:
            return resp.content
    except Exception as e:
        logger.warning("Failed to read file via HTTP %s: %s", url, e)
    raise FileNotFoundError(url)


def _save_pwa_icons(source_url: str):
    if not source_url:
        return
    try:
        data = _read_storage_file(source_url)
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA")
        storage = get_storage()
        for size in (192, 512):
            resized = img.resize((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            buf.seek(0)
            storage.save(f"pwa/icon-{size}.png", buf.getvalue(), "image/png")
    except Exception as e:
        logger.warning("Failed to save PWA icons: %s", e)


def _save_favicon(source_url: str):
    if not source_url:
        return
    try:
        data = _read_storage_file(source_url)
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA")
        resized = img.resize((32, 32), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        buf.seek(0)
        storage = get_storage()
        storage.save("pwa/favicon.png", buf.getvalue(), "image/png")
    except Exception as e:
        logger.warning("Failed to save favicon: %s", e)


def _delete_favicon():
    try:
        get_storage().delete("pwa/favicon.png")
    except Exception:
        pass


def _delete_pwa_icons():
    """Remove PWA icons from storage, restoring default."""
    storage = get_storage()
    for size in (192, 512):
        try:
            storage.delete(f"pwa/icon-{size}.png")
        except Exception:
            pass


@router.get("/pwa/manifest")
def api_pwa_manifest():
    with get_session() as s:
        settings = ServerSetting.get(s)
        name = settings.server_name or "WRIT"
        app_icon = settings.app_icon or ""
    icons = []
    for size in (192, 512):
        if app_icon:
            icons.append({"src": f"/api/pwa/icon/{size}", "sizes": f"{size}x{size}", "type": "image/png"})
        else:
            icons.append({"src": f"/icons/icon-{size}.png", "sizes": f"{size}x{size}", "type": "image/png"})
    return {
        "name": name,
        "short_name": name,
        "description": "작가를 위한 소셜 네트워크",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#689f38",
        "theme_color": "#689f38",
        "orientation": "portrait",
        "categories": ["social", "books", "writing"],
        "icons": icons,
    }


@router.get("/pwa/favicon")
def api_pwa_favicon():
    storage = get_storage()
    try:
        data = storage.get("pwa/favicon.png")
        if data:
            logger.info("[favicon] serving custom favicon (%d bytes)", len(data))
            return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-cache, max-age=0", "Vary": "Accept-Encoding"})
    except Exception as e:
        logger.info("[favicon] no custom favicon: %s", e)
    for path in [
        os.path.join(os.path.dirname(__file__), "..", "..", "static", "favicon.ico"),
        os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "favicon.ico"),
    ]:
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache, max-age=0"})
    return JSONResponse({"error": "Not found"}, status_code=404)


@router.get("/pwa/icon/{size}")
def api_pwa_icon(size: int):
    storage = get_storage()
    try:
        data = storage.get(f"pwa/icon-{size}.png")
        if data:
            return Response(content=data, media_type="image/png")
    except Exception:
        pass
    # Fallback to default icon
    default_path = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "icons", f"icon-{size}.png")
    if os.path.exists(default_path):
        return FileResponse(default_path, media_type="image/png")
    return JSONResponse({"error": "Not found"}, status_code=404)


# Admin endpoints moved to app/routes.api._admin


@router.post("/log")
def api_client_log(request: Request):
    """Receive log events from the frontend."""
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


# ── Web Push ──

@router.get("/push/vapid-public-key")
def get_vapid_public_key():
    key = VAPID_PUBLIC_KEY
    if not key:
        try:
            _k = ec.generate_private_key(ec.SECP256R1())
            _priv_pem = _k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
            _raw_pub = _k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            key = base64.urlsafe_b64encode(_raw_pub).rstrip(b"=").decode()
            os.environ["VAPID_PRIVATE_KEY"] = _priv_pem
            os.environ["VAPID_PUBLIC_KEY"] = key
            print("[PUSH] Auto-generated VAPID keys", flush=True)
        except Exception as e:
            print(f"[PUSH] Failed to generate VAPID key: {e}", flush=True)
            raise HTTPException(500, "Web Push configuration error")
    if key.startswith("-----"):
        pub = load_pem_public_key(key.encode())
        if isinstance(pub, ec.EllipticCurvePublicKey):
            raw = pub.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
            key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"publicKey": key}


@router.post("/push/subscribe")
def subscribe_push(request: Request, endpoint: str = Form(...), p256dh: str = Form(...), auth: str = Form(...), device_name: str = Form("")):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).first()
        if existing:
            existing.p256dh = p256dh
            existing.auth = auth
            if device_name:
                existing.device_name = device_name
        else:
            s.add(PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, device_name=device_name))
        s.commit()
    return {"ok": True}


@router.post("/push/unsubscribe")
def unsubscribe_push(request: Request, endpoint: str = Form(...)):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).delete()
        s.commit()
    return {"ok": True}


@router.get("/push/subscriptions")
def push_subscriptions(request: Request):
    user = require_active_auth(request)
    with get_session() as s:
        subs = s.query(PushSubscription).filter_by(user_id=user.id).all()
    return {"subscriptions": [{"id": sub.id, "device_name": sub.device_name, "created_at": sub.created_at.isoformat() if sub.created_at else ""} for sub in subs]}


@router.post("/push/subscriptions/{sub_id}/delete")
def delete_push_subscription(request: Request, sub_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        sub = s.query(PushSubscription).filter_by(id=sub_id, user_id=user.id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        s.delete(sub)
        s.commit()
    return {"ok": True}


@router.get("/push/status")
def push_status(request: Request):
    user = require_active_auth(request)
    with get_session() as s:
        count = s.query(PushSubscription).filter_by(user_id=user.id).count()
    return {"subscribed": count > 0}


# ── Login session management ──

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


@router.get("/sessions")
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


@router.post("/sessions/{session_id}/delete")
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
