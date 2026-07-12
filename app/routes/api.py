import os
import re
import json
import asyncio
import datetime
import uuid
import logging
import threading
from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import desc, or_, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, SeriesFollow, SeriesNotice, Tag, CustomEmoji, ProfileNote, Report, ServerRule, BlockedDomain, FederationBlock, AllowedServer, MutedServer, ServerSetting, AdminLog, UserMute, UserBlock, SeriesMute, KeywordMute, EpisodeView, PendingDelivery, PushSubscription, get_session
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.log_utils import log_admin_action

KST = datetime.timezone(datetime.timedelta(hours=9))

def _fmt_dt(dt: datetime.datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(KST).isoformat()
from app.activitypub import broadcast_to_followers, _post_to_inbox, _process_emoji_tags, _federation_allowed
from app.config import BASE_URL, MAX_POST_LENGTH, SECRET_KEY
from app.crypto_utils import encrypt_key, get_private_key
from app.eventbus import broadcast
from app.timeline_stream import broadcast_post, add_stream, remove_stream, broadcast_refresh_notifs, add_notif_stream, remove_notif_stream
from app.utils.storage import LocalStorage

logger = logging.getLogger("writ.api")

RESERVED_HANDLES = frozenset({
    "admin", "administrator", "root", "system", "moderator", "support",
    "nodeinfo", "well-known", "api", "auth", "oauth", "inbox", "outbox",
    "actor", "users", "accounts", "instance_actor", "login", "register", "writ",
})

router = APIRouter(prefix="/api")


# ── helpers ──

def _post_json(p, session, user, tl_type=None):
    liked = session.query(Like).filter_by(user_id=user.id, post_id=p.id).first() is not None if user else False
    boosted = session.query(Boost).filter_by(user_id=user.id, post_id=p.id).first() is not None if user else False
    bookmarked = session.query(Bookmark).filter_by(user_id=user.id, post_id=p.id).first() is not None if user else False
    booster = None
    if p.author_id != (user.id if user else 0):
        latest_boost = session.query(Boost).filter_by(post_id=p.id).order_by(desc(Boost.created_at)).first()
        if latest_boost:
            import datetime as _dt
            if (_dt.datetime.now(_dt.timezone.utc) - latest_boost.created_at).total_seconds() > 10800:
                booster = session.query(User).get(latest_boost.user_id)
    my_vote = None
    if user and p.poll_data:
        vote = session.query(Vote).filter_by(user_id=user.id, post_id=p.id).first()
        if vote:
            my_vote = vote.option_index
    my_reaction = None
    if user and liked:
        my_reaction = session.query(Like.reaction).filter_by(user_id=user.id, post_id=p.id).scalar()
    reactions = {}
    _default_react = "★"
    if p.likes:
        _has_custom = False
        for like in p.likes:
            if like.reaction:
                reactions[like.reaction] = reactions.get(like.reaction, 0) + 1
                _has_custom = True
            else:
                reactions[_default_react] = reactions.get(_default_react, 0) + 1
    return {
        "id": p.id,
        "number": p.number or "",
        "content": p.content,
        "summary": p.summary or "",
        "visibility": p.visibility or "public",
        "created_at": _fmt_dt(p.created_at),
        "author": _user_json(p.author),
        "likes_count": p.likes_count,
        "boosts_count": p.boosts_count,
        "replies_count": p.replies_count,
        "liked": liked,
        "boosted": boosted,
        "bookmarked": bookmarked,
        "is_mine": p.author_id == user.id if user else False,
        "is_dm": p.is_dm or False,
        "is_sensitive": getattr(p, 'is_sensitive', False) or False,
        "ap_id": p.ap_id or "",
        "reply_context": _reply_context(p, session, user, tl_type),
        "boosted_by": _user_json(booster) if booster and booster.id != p.author_id else None,
        "media_attachments": (p.media_attachments or []) if hasattr(p, 'media_attachments') else [],
        "poll_data": p.poll_data,
        "my_vote": my_vote,
        "reactions": reactions,
        "my_reaction": my_reaction,
        "mentioned_user_ids": p.mentioned_user_ids or [],
        "mentioned_handles": [u.username for u in (session.query(User).filter(User.id.in_(p.mentioned_user_ids or [])).all())] if p.mentioned_user_ids else [],
        "link_preview": p.link_preview or None,
    }


def _user_json(u):
    role = getattr(u, 'role', 'user') or 'user'
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "avatar": u.profile_image or "",
        "header": u.header_image or "",
        "summary": u.summary or "",
        "is_admin": u.is_admin,
        "is_locked": u.is_locked or False,
        "is_limited": u.is_limited or False,
        "is_frozen": getattr(u, 'is_frozen', False) or False,
        "is_deceased": getattr(u, 'is_deceased', False) or False,
        "is_deactivated": getattr(u, 'is_deactivated', False) or False,
        "is_sensitive": getattr(u, 'is_sensitive', False) or False,
        "is_remote": u.is_remote,
        "role": role,
        "show_badge": getattr(u, 'show_badge', False) or False,
        "email_verified": u.email_verified or False,
        "default_visibility": u.default_visibility or "public",
        "display_handle": getattr(u, 'display_handle', '') or "",
        "is_bot": getattr(u, 'is_bot', False) or False,
        "pinned_posts": (u.pinned_posts or []) if hasattr(u, 'pinned_posts') else [],
        "pinned_series": (u.pinned_series or []) if hasattr(u, 'pinned_series') else [],
        "episode_default_visibility": u.episode_default_visibility or "public",
        "follow_list_visibility": getattr(u, 'follow_list_visibility', 'public') or 'public',
        "custom_fields": (u.custom_fields or []) if hasattr(u, 'custom_fields') else [],
        "profile_hashtags": (u.profile_hashtags or []) if hasattr(u, 'profile_hashtags') else [],
        "enable_reactions": getattr(u, 'enable_reactions', True),
        "aliases": (u.aliases or []) if hasattr(u, 'aliases') else [],
        "moved_to": getattr(u, 'moved_to', '') or '',
    }


def _reply_context(p, session=None, user=None, tl_type=None):
    parent = p.parent if hasattr(p, 'parent') else None
    if not parent and p.in_reply_to_ap_id and session:
        try:
            parent = session.query(Post).filter_by(ap_id=p.in_reply_to_ap_id).first()
        except Exception:
            pass
    if not parent:
        return None
    if tl_type == "home" and user and parent.author_id != user.id:
        followed = session.query(Follow).filter_by(
            follower_id=user.id, following_id=parent.author_id, accepted=True
        ).first()
        if not followed:
            return None
    if tl_type == "local" and parent.author.is_remote:
        return None
    return {
        "id": parent.id,
        "number": parent.number or "",
        "content": parent.content[:200] if parent.content else "",
        "author": _user_json(parent.author),
        "visibility": parent.visibility or "public",
    }


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


def _parse_mentions(content):
    mentioned = set(re.findall(r'@(\w+(?:@[\w.-]+)?)', content))
    if not mentioned:
        return []
    with get_session() as s:
        users = s.query(User).filter(User.username.in_(mentioned)).all()
        return [u.id for u in users]


def _sync_post_tags(post, s):
    """Parse #hashtags from post content and sync with Tag model."""
    tags = set(re.findall(r'(?<!\w)#([\w_가-힣]+)', post.content))
    desired = set(t.lower() for t in tags)
    current = {t.name for t in (post.tag_list or [])}
    for name in desired - current:
        tag = s.query(Tag).filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            s.add(tag)
            s.flush()
        post.tag_list.append(tag)
    for name in current - desired:
        tag = next((t for t in post.tag_list if t.name == name), None)
        if tag:
            post.tag_list.remove(tag)


TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


# ── Auth API ──

@router.get("/auth/me")
def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    result = _user_json(user)
    from app.models import ServerSetting as _SS
    with get_session() as _s:
        _settings = _SS.get(_s)
        if not _settings.enable_reactions:
            result["enable_reactions"] = False
    return result


@router.post("/auth/login")
def api_login(request: Request, username: str = Form(...), password: str = Form(...)):
    from app.routes.auth import hash_password, verify_password, create_session
    try:
        client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0].strip()
        with get_session() as s:
            q = s.query(User).filter(User.is_remote == False)
            if "@" in username and "." in username:
                db_user = q.filter(User.email == username).first()
            else:
                db_user = q.filter(User.username == username).first()
            if not db_user:
                log_admin_action(None, username, "login_failed", details="user_not_found", ip_address=client_ip)
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
                raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
            if not db_user.email_verified:
                log_admin_action(db_user.id, db_user.username, "login_blocked", details="email_not_verified", ip_address=client_ip)
                raise HTTPException(status_code=403, detail="이메일 인증이 필요합니다. 가입 시 등록한 이메일에서 인증을 완료해 주세요.")
            token = create_session(db_user.id)
            if client_ip:
                ips = db_user.recent_ips or []
                ips = [ip for ip in ips if ip != client_ip]
                ips.insert(0, client_ip)
                db_user.recent_ips = ips[:10]
                s.commit()
            log_admin_action(db_user.id, db_user.username, "login", ip_address=client_ip)
            resp = JSONResponse(_user_json(db_user))
            resp.set_cookie(key="session", value=token, max_age=30*86400, httponly=True, samesite="lax", path="/")
            return resp
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Login error")
        raise HTTPException(status_code=500, detail=str(exc))


def _send_verification_email(u: User):
    import secrets
    from app.config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, APP_ENV
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
        from email.mime.text import MIMEText
        import smtplib
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
    from app.routes.auth import hash_password
    from app.crypto_utils import generate_keypair
    import secrets
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
        from app.config import INITIAL_OWNER_PASSWORD
        if is_first and INITIAL_OWNER_PASSWORD and password != INITIAL_OWNER_PASSWORD:
            raise HTTPException(status_code=400, detail="초기 관리자 암호가 일치하지 않습니다.")
        salt, pwd_hash = hash_password(password)
        priv_key, pub_key = generate_keypair()
        email_verified = is_first
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

        if not is_first:
            try:
                _send_verification_email(user)
            except Exception:
                pass
        s.commit()

        log_admin_action(user_id, user.username, "register", ip_address=client_ip, details="first_user" if is_first else "email_required")

        if is_first:
            from app.routes.auth import create_session
            sess = create_session(user.id)
            resp = JSONResponse({"ok": True, "email_sent": not is_first})
            resp.set_cookie(key="session", value=sess, max_age=30*86400, httponly=True, samesite="lax", path="/")
            return resp
        return {"ok": True, "email_sent": not is_first}


@router.post("/auth/verify-email")
def api_verify_email(request: Request, token: str = Form(...)):
    from app.routes.auth import create_session
    with get_session() as s:
        u = s.query(User).filter_by(verification_token=token).first()
        if not u:
            # Check if already verified (token was cleared by a previous request)
            u = s.query(User).filter_by(email_verified=True, verification_token="").first()
            if u:
                sess = create_session(u.id)
                resp = JSONResponse({"ok": True, "email_verified": True, "already_verified": True})
                resp.set_cookie(key="session", value=sess, max_age=30*86400, httponly=True, samesite="lax", path="/")
                return resp
            raise HTTPException(status_code=400, detail="유효하지 않은 인증 토큰입니다.")
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
        sess = create_session(u.id)
        resp = JSONResponse({"ok": True, "email_verified": True})
        resp.set_cookie(key="session", value=sess, max_age=30*86400, httponly=True, samesite="lax", path="/")
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


@router.post("/auth/logout")
def api_logout(request: Request):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp


# ── Timeline API ──

def _get_feed(user, tl_type, session, limit=10, offset=0):
    if tl_type == "home":
        following_ids = [f.following_id for f in session.query(Follow).filter_by(
            follower_id=user.id, accepted=True
        ).all()]
        following_ids.append(user.id)
        boosted_ids = [b.post_id for b in session.query(Boost).filter_by(user_id=user.id).all()]
        posts = session.query(Post).options(
            selectinload(Post.parent).selectinload(Post.author)
        ).filter(
            or_(
                Post.author_id.in_(following_ids),
                Post.id.in_(boosted_ids),
            ),
            Post.is_deleted == False,
            or_(Post.visibility != "home", Post.author_id.in_(following_ids)),
        ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).offset(offset).limit(limit + 1).all()
    elif tl_type == "social":
        following_ids = [f.following_id for f in session.query(Follow).filter_by(
            follower_id=user.id, accepted=True
        ).all()]
        following_ids.append(user.id)
        local_ids = [u.id for u in session.query(User).filter_by(is_remote=False).all()]
        posts = session.query(Post).options(
            selectinload(Post.parent).selectinload(Post.author)
        ).filter(
            or_(
                Post.author_id.in_(following_ids),
                and_(Post.author_id.in_(local_ids), Post.visibility == "public"),
            ),
            Post.is_deleted == False,
        ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).offset(offset).limit(limit + 1).all()
    elif tl_type == "local":
        local_ids = [u.id for u in session.query(User).filter_by(is_remote=False).all()]
        posts = session.query(Post).options(
            selectinload(Post.parent).selectinload(Post.author)
        ).filter(
            Post.author_id.in_(local_ids),
            Post.visibility == "public",
            Post.is_deleted == False,
        ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).offset(offset).limit(limit + 1).all()
    else:
        posts = session.query(Post).options(
            selectinload(Post.parent).selectinload(Post.author)
        ).filter(
            Post.visibility == "public",
            Post.is_deleted == False,
        ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).offset(offset).limit(limit + 1).all()
    raw_total = len(posts)
    posts = [p for p in posts if not (p.visibility == "mention" and p.is_dm and p.author_id != user.id and user.id not in (p.mentioned_user_ids or []))]
    # Filter replies: only show if all thread participants are followed (or post is mine)
    # Only for home/social timelines, not local/federated
    if user and tl_type in ("home", "social"):
        following_ids = {f.following_id for f in session.query(Follow).filter_by(
            follower_id=user.id, accepted=True
        ).all()}
        following_ids.add(user.id)
        reply_filtered = []
        for p in posts:
            if p.author_id != user.id and (p.in_reply_to_id or p.in_reply_to_ap_id):
                participants = set()
                # Walk local parent chain only (no HTTP fetches)
                cur = p
                depth = 0
                while cur and depth < 20:
                    parent = getattr(cur, 'parent', None)
                    if not parent:
                        break
                    participants.add(parent.author_id)
                    cur = parent
                    depth += 1
                if participants and not participants <= following_ids:
                    continue
            reply_filtered.append(p)
        posts = reply_filtered
    # Apply user mutes, blocks, and keyword mutes
    if user:
        muted_user_ids = {m.target_user_id for m in session.query(UserMute).filter_by(user_id=user.id).all()}
        blocked_ids = {b.target_user_id for b in session.query(UserBlock).filter_by(user_id=user.id).all()}
        blocked_by_ids = {b.user_id for b in session.query(UserBlock).filter_by(target_user_id=user.id).all()}
        muted_series_ids = {m.novel_id for m in session.query(SeriesMute).filter_by(user_id=user.id).all()}
        hidden_ids = muted_user_ids | blocked_ids | blocked_by_ids
        kw_mutes = session.query(KeywordMute).filter_by(user_id=user.id).all()
        import re
        filtered = []
        for p in posts:
            if p.author_id in hidden_ids:
                continue
            # Check series mute
            if p.novel_id and p.novel_id in muted_series_ids:
                continue
            # Check keyword mutes
            if kw_mutes:
                matched = False
                content_lower = (p.content or "").lower()
                for kw in kw_mutes:
                    if kw.is_regex:
                        try:
                            if re.search(kw.keyword, content_lower):
                                matched = True
                                break
                        except re.error:
                            pass
                    else:
                        import json
                        try:
                            keywords = json.loads(kw.keyword)
                            if isinstance(keywords, str):
                                keywords = [keywords]
                        except (json.JSONDecodeError, TypeError):
                            keywords = [kw.keyword]
                        keywords = [k.strip().lower() for k in keywords if k.strip()]
                        if kw.mode == "and":
                            if all(k in content_lower for k in keywords):
                                matched = True
                                break
                        else:
                            if any(k in content_lower for k in keywords):
                                matched = True
                                break
                if matched:
                    continue
            filtered.append(p)
        posts = filtered
    has_more = raw_total > limit
    return [_post_json(p, session, user, tl_type) for p in posts[:limit]], has_more


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


@router.get("/timeline/{tl_type}")
def api_timeline(request: Request, tl_type: str, limit: int = Query(10), offset: int = Query(0)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if getattr(user, 'is_deactivated', False):
        return JSONResponse({"error": "Account deactivated"}, status_code=403)
    if tl_type not in TIMELINE_LABELS:
        tl_type = "home"
    with get_session() as s:
        feed, has_more = _get_feed(user, tl_type, s, limit=limit, offset=offset)
    return {"posts": feed, "timeline_type": tl_type, "has_more": has_more}


# ── Post CRUD ──

@router.get("/posts/{post_id}")
def api_get_post(request: Request, post_id: int):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        post = s.query(Post).options(
            selectinload(Post.author),
            selectinload(Post.parent).selectinload(Post.author),
        ).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=403, detail="Cannot view this post")
        result = _post_json(post, s, user)
        if user and post.author_id != user.id:
            result["is_following_author"] = s.query(Follow).filter_by(
                follower_id=user.id, following_id=post.author_id, accepted=True
            ).first() is not None
        else:
            result["is_following_author"] = False
        descendant_ids = set()
        def collect_descendants(pid):
            children = s.query(Post).options(selectinload(Post.author)).filter_by(
                in_reply_to_id=pid, is_deleted=False
            ).all()
            for c in children:
                if c.id not in descendant_ids:
                    descendant_ids.add(c.id)
                    collect_descendants(c.id)
        collect_descendants(post_id)
        direct_count = s.query(Post).filter_by(in_reply_to_id=post_id, is_deleted=False).count()
        total_descendants = len(descendant_ids)
        result["total_replies"] = direct_count
        result["total_descendants"] = total_descendants
        limit = min(int(request.query_params.get("reply_limit", 5)), 50)
        offset = int(request.query_params.get("reply_offset", 0))
        reply_ids = sorted(descendant_ids)[offset:offset + limit]
        descendants = s.query(Post).options(selectinload(Post.parent)).filter(
            Post.id.in_(reply_ids)
        ).order_by(Post.created_at).all() if reply_ids else []
        result["replies"] = [_post_json(r, s, user) for r in descendants if _can_view(r, user, s)]
        result["has_more_replies"] = offset + limit < total_descendants
        # ancestors
        ancestors = []
        cur = post.parent
        while cur:
            ancestors.insert(0, _post_json(cur, s, user))
            cur = cur.parent
        if not ancestors and post.in_reply_to_ap_id:
            try:
                parent = s.query(Post).filter_by(ap_id=post.in_reply_to_ap_id).first()
                if not parent:
                    from app.activitypub import _fetch_remote_post
                    parent = _fetch_remote_post(post.in_reply_to_ap_id, user, s)
                if parent:
                    ancestors = [_post_json(parent, s, user)]
            except Exception:
                pass
        result["ancestors"] = ancestors
    return result


def _broadcast_federation(user, post, visibility):
    """Deliver Create activity to remote followers (background thread)."""
    try:
        create_activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{BASE_URL}/activities/create/{post.id}",
            "type": "Create",
            "actor": user.actor_uri(),
            "object": post.to_ap_note(),
        }
        if visibility == "mention" and post.mentioned_user_ids:
            with get_session() as ap_s:
                mu_users = ap_s.query(User).filter(
                    User.id.in_(post.mentioned_user_ids), User.is_remote == True
                ).all()
                for mu in mu_users:
                    inbox = mu.inbox_url or mu.inbox_uri()
                    domain = mu.actor_uri().split("/")[2] if "//" in mu.actor_uri() else ""
                    if domain and not _federation_allowed(domain):
                        continue
                    _post_to_inbox(inbox, create_activity, user)
        else:
            broadcast_to_followers(user, create_activity)
            if post.mentioned_user_ids:
                with get_session() as ap_s:
                    follower_ids = {f.following_id for f in ap_s.query(Follow).filter(
                        Follow.following_id == user.id,
                        Follow.follower.has(is_remote=True),
                    ).all()}
                    mu_users = ap_s.query(User).filter(
                        User.id.in_(post.mentioned_user_ids), User.is_remote == True
                    ).all()
                    for mu in mu_users:
                        if mu.id not in follower_ids:
                            inbox = mu.inbox_url or mu.inbox_uri()
                            domain = mu.actor_uri().split("/")[2] if "//" in mu.actor_uri() else ""
                            if domain and not _federation_allowed(domain):
                                continue
                            _post_to_inbox(inbox, create_activity, user)
    except Exception as e:
        logger.warning("Failed to broadcast federation activity: %s", e)


def _broadcast_update_actor(user):
    """Deliver Update actor activity to remote followers (background thread)."""
    try:
        update = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{user.actor_uri()}#updates/{uuid.uuid4()}",
            "type": "Update",
            "actor": user.actor_uri(),
            "object": user.to_ap_actor(),
        }
        broadcast_to_followers(user, update)
    except Exception as e:
        logger.warning("Failed to broadcast Update actor: %s", e)


def _broadcast_timeline(post_json, author_id, visibility, is_dm):
    """Deliver post to connected timeline streams (background thread)."""
    try:
        broadcast_post(post_json, author_id, visibility, is_dm)
    except Exception as e:
        logger.warning("Failed to broadcast timeline: %s", e)


@router.post("/posts")
def api_create_post(
    request: Request,
    content: str = Form(...),
    summary: str = Form(""),
    visibility: str = Form("public"),
    parent_id: int = Form(None),
    dm_target_id: int = Form(None),
    share_url: str = Form(""),
    media_attachments: str = Form("[]"),
    is_sensitive: bool = Form(False),
    poll_options: str = Form(""),
    poll_expires_in: int = Form(60),
    link_preview: str = Form(""),
):
    user = require_active_auth(request)
    if share_url:
        if "/episodes/" in share_url:
            content = content + "\n\nepisode: " + share_url
        else:
            content = content + "\n\nseries: " + share_url
    if not content.strip() and not poll_options:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    total_len = len(content) + len(summary)
    if total_len > MAX_POST_LENGTH:
        raise HTTPException(status_code=400, detail=f"Total length exceeds {MAX_POST_LENGTH}")
    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"

    if user.is_limited and visibility == "public":
        visibility = "home"

    if parent_id:
        vis_order = {"public": 0, "home": 1, "followers": 2, "mention": 3}
        with get_session() as _s:
            parent_post = _s.query(Post).filter_by(id=parent_id).first()
            if parent_post:
                parent_vis = parent_post.visibility or "public"
                if vis_order.get(parent_vis, 0) > vis_order.get(visibility, 0):
                    visibility = parent_vis

    mentioned_ids = _parse_mentions(content)
    if dm_target_id and dm_target_id not in mentioned_ids:
        mentioned_ids.append(dm_target_id)
    with get_session() as s:
        import secrets
        post_number = secrets.token_hex(4)
        author_is_sensitive = getattr(user, 'is_sensitive', False) or False
        post = Post(
            author_id=user.id,
            content=content,
            summary=summary,
            visibility=visibility,
            in_reply_to_id=parent_id,
            mentioned_user_ids=mentioned_ids,
            number=post_number,
            ap_id="",
            is_dm=bool(dm_target_id),
            is_sensitive=is_sensitive or author_is_sensitive,
        )
        import json as _json
        if link_preview:
            try:
                post.link_preview = _json.loads(link_preview)
            except (_json.JSONDecodeError, TypeError):
                pass
        try:
            media = _json.loads(media_attachments)
            if isinstance(media, list):
                post.media_attachments = media[:16]
        except (_json.JSONDecodeError, TypeError):
            pass
        if poll_options:
            try:
                opts = _json.loads(poll_options)
                if isinstance(opts, list) and 2 <= len(opts) <= 10 and all(isinstance(o, str) and o.strip() for o in opts):
                    now = datetime.datetime.now(datetime.timezone.utc)
                    expires_at = (now + datetime.timedelta(minutes=poll_expires_in)).isoformat() if poll_expires_in > 0 else None
                    post.poll_data = {
                        "options": [{"text": o.strip(), "votes_count": 0} for o in opts],
                        "expires_at": expires_at,
                    }
            except (_json.JSONDecodeError, TypeError):
                pass
        s.add(post)
        s.flush()
        post.ap_id = f"{BASE_URL}/@{user.username}/{post.number}"
        _sync_post_tags(post, s)
        if parent_id:
            parent = s.query(Post).filter_by(id=parent_id).first()
            if parent:
                post.in_reply_to_ap_id = parent.ap_id or ""
        s.commit()

        # notify mentioned users
        for mu_id in mentioned_ids:
            if mu_id != user.id:
                notif = Notification(user_id=mu_id, from_user_id=user.id, notification_type="mention", post_id=post.id)
                s.add(notif)
        if parent_id:
            parent = s.query(Post).filter_by(id=parent_id).first()
            if parent and parent.author_id != user.id:
                notif = Notification(user_id=parent.author_id, from_user_id=user.id, notification_type="reply", post_id=post.id)
                s.add(notif)
        s.commit()

        from app.push import send_push_to_user
        for mu_id in mentioned_ids:
            if mu_id != user.id:
                send_push_to_user(mu_id, "mention", user.username, post.id)
        if parent_id:
            parent = s.query(Post).filter_by(id=parent_id).first()
            if parent and parent.author_id != user.id and parent.author_id not in [mid for mid in mentioned_ids if mid != user.id]:
                send_push_to_user(parent.author_id, "reply", user.username, post.id)

        # Async federation broadcast (background thread so it doesn't block response)
        threading.Thread(target=_broadcast_federation, args=(user, post, visibility), daemon=True).start()

        try:
            broadcast("new_post", {"post_id": post.id, "author_id": user.id})
        except Exception as e:
            logger.warning("Failed to broadcast new_post event: %s", e)

        pj = _post_json(post, s, user)
        threading.Thread(target=_broadcast_timeline, args=(pj, user.id, visibility, bool(dm_target_id)), daemon=True).start()
        return pj


@router.post("/posts/{post_id}/edit")
def api_edit_post(request: Request, post_id: int, content: str = Form(...), summary: str = Form("")):
    user = require_active_auth(request)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id:
            raise HTTPException(status_code=403, detail="Cannot edit this post")
        if post.summary and post.summary.startswith("[관리자 강제] ") and not summary.startswith("[관리자 강제] "):
            raise HTTPException(status_code=403, detail="관리자가 강제한 CW는 수정할 수 없습니다")
        post.content = content
        post.summary = summary
        s.commit()
        return _post_json(post, s, user)


@router.post("/posts/{post_id}/delete")
def api_delete_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id and not user.is_admin:
            raise HTTPException(status_code=403, detail="Cannot delete this post")
        # Delete attached media files
        if post.media_attachments:
            from app.utils.storage import get_storage
            storage = get_storage()
            for m in post.media_attachments:
                if isinstance(m, dict) and m.get("url"):
                    storage.delete(m["url"])
        post.is_deleted = True
        # Clean up notifications referencing this post
        s.query(Notification).filter_by(post_id=post.id).delete()
        s.commit()
        if post.ap_id and post.ap_id.startswith("http") and not post.author.is_remote:
            from app.activitypub import _send_delete_post
            _send_delete_post(post, user)
    return {"ok": True}


@router.post("/reports")
def api_create_report(request: Request, target_type: str = Form(...), target_id: int = Form(...), reason: str = Form(...), forward_to_remote: bool = Form(False), rule_ids: str = Form("")):
    user = require_active_auth(request)
    target_type = target_type.strip().lower()
    if target_type not in ("post", "novel", "episode"):
        raise HTTPException(status_code=400, detail="Invalid target_type")
    if forward_to_remote:
        import datetime as _dt
        _cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=1)
        with get_session() as _s:
            _recent = _s.query(Report).filter(
                Report.reporter_id == user.id,
                Report.forward_to_remote == True,
                Report.created_at >= _cutoff,
            ).count()
            if _recent >= 3:
                raise HTTPException(status_code=429, detail="원격 신고는 1분에 3회까지 가능합니다")
    parsed_rule_ids = []
    if rule_ids and rule_ids.strip():
        try:
            parsed = json.loads(rule_ids)
            if isinstance(parsed, list):
                parsed_rule_ids = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if not reason or len(reason.strip()) < 10:
        if not parsed_rule_ids:
            raise HTTPException(status_code=400, detail="Reason must be at least 10 characters")
    with get_session() as s:
        existing = s.query(Report).filter_by(
            reporter_id=user.id, target_type=target_type, target_id=target_id, status="pending"
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Already reported")
        report = Report(reporter_id=user.id, target_type=target_type, target_id=target_id, reason=reason.strip(), forward_to_remote=forward_to_remote, rule_ids=parsed_rule_ids)
        s.add(report)
        s.flush()
        report_id = report.id
        admins = s.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
        target_label = ""
        target_author_name = ""
        target_obj = None
        if target_type == "post":
            target_obj = s.query(Post).filter_by(id=target_id).first()
            if target_obj:
                target_label = (target_obj.content or "")[:120]
                target_author_name = target_obj.author.username
        elif target_type == "novel":
            target_obj = s.query(Novel).filter_by(id=target_id).first()
            if target_obj:
                target_label = target_obj.title[:120]
                target_author_name = target_obj.author.username
        elif target_type == "episode":
            target_obj = s.query(Episode).filter_by(id=target_id).first()
            if target_obj:
                target_label = target_obj.title[:120]
                target_author_name = target_obj.novel.author.username if target_obj.novel else ""
        meta = {
            "type": "report",
            "report_id": report_id,
            "target_type": target_type,
            "target_id": target_id,
            "target_label": target_label,
            "target_author": target_author_name,
            "reason": reason.strip()[:200],
        }
        for admin in admins:
            if admin.id == user.id:
                continue
            s.add(Notification(
                user_id=admin.id, from_user_id=user.id,
                notification_type="moderation",
                metadata_json=json.dumps(meta),
            ))
        s.commit()
        from app.timeline_stream import broadcast_refresh_notifs
        broadcast_refresh_notifs()
        from app.push import send_push_to_user
        for admin in admins:
            if admin.id != user.id:
                send_push_to_user(admin.id, "moderation", user.username)

        if forward_to_remote and target_obj and hasattr(target_obj, 'author') and target_obj.author and target_obj.author.is_remote:
            try:
                from app.activitypub import _send_flag
                _send_flag(user, target_type, target_obj, reason.strip()[:200], parsed_rule_ids)
            except Exception as e:
                logger.warning("Failed to send Flag activity: %s", e)
    return {"ok": True, "report_id": report_id}


@router.get("/rules")
def api_list_rules():
    with get_session() as s:
        rules = s.query(ServerRule).order_by(ServerRule.sort_order).all()
        return [{"id": r.id, "title": r.title, "description": r.description, "sort_order": r.sort_order} for r in rules]


@router.post("/posts/{post_id}/like")
def api_like_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        if not existing:
            s.add(Like(user_id=user.id, post_id=post_id))
            if post.author_id != user.id:
                s.add(Notification(user_id=post.author_id, from_user_id=user.id, notification_type="like", post_id=post_id))
            s.commit()
            if post.author_id != user.id:
                broadcast_refresh_notifs()
                from app.push import send_push_to_user
                send_push_to_user(post.author_id, "like", user.username, post_id)
        if post.author.is_remote and post.author.shared_inbox_url:
            like_id = f"{BASE_URL}/likes/{uuid.uuid4()}"
            like_rec = existing or s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
            if like_rec:
                like_rec.ap_id = like_id
                s.commit()
            like_activity = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": like_id,
                "type": "Like",
                "actor": user.actor_uri(),
                "object": post.ap_id,
                "to": [post.author.actor_uri()],
                "cc": [],
            }
            inbox = post.author.shared_inbox_url
            try:
                _post_to_inbox(inbox, like_activity, user)
            except Exception:
                pass
    return {"ok": True}


@router.post("/posts/{post_id}/unlike")
def api_unlike_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        like_id = existing.ap_id if existing and existing.ap_id else ""
        if existing:
            s.delete(existing)
            s.query(Notification).filter_by(
                from_user_id=user.id, notification_type="like", post_id=post_id
            ).delete()
            s.commit()
            broadcast_refresh_notifs()
        if post.author.is_remote and post.author.shared_inbox_url:
            undo = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/likes/{uuid.uuid4()}#undo",
                "type": "Undo",
                "actor": user.actor_uri(),
                "object": {
                    "id": like_id or f"{BASE_URL}/likes/{uuid.uuid4()}",
                    "type": "Like",
                    "actor": user.actor_uri(),
                    "object": post.ap_id,
                },
            }
            inbox = post.author.shared_inbox_url
            try:
                _post_to_inbox(inbox, undo, user)
            except Exception:
                pass
    return {"ok": True}


@router.post("/posts/{post_id}/boost")
def api_boost_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
        if not existing:
            s.add(Boost(user_id=user.id, post_id=post_id))
            three_hours_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
            twentieth = s.query(Post.created_at).filter(
                Post.is_deleted == False,
            ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).offset(19).limit(1).scalar()
            if (twentieth and post.created_at and post.created_at < twentieth
                and post.created_at < three_hours_ago):
                post.bumped_at = datetime.datetime.now(datetime.timezone.utc)
            if post.author_id != user.id:
                s.add(Notification(user_id=post.author_id, from_user_id=user.id, notification_type="boost", post_id=post_id))
            s.commit()
            broadcast_refresh_notifs()
            if post.author_id != user.id:
                from app.push import send_push_to_user
                send_push_to_user(post.author_id, "boost", user.username, post_id)
        if post.author.is_remote and post.author.shared_inbox_url:
            announce_id = f"{BASE_URL}/boosts/{uuid.uuid4()}"
            # Store the activity ID so Unboosts can reference it
            boost_rec = existing or s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
            if boost_rec:
                boost_rec.ap_id = announce_id
                s.commit()
            announce = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": announce_id,
                "type": "Announce",
                "actor": user.actor_uri(),
                "object": post.ap_id,
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [post.author.actor_uri()],
            }
            inbox = post.author.shared_inbox_url
            try:
                _post_to_inbox(inbox, announce, user)
            except Exception:
                pass
    return {"ok": True}


@router.post("/posts/{post_id}/bookmark")
def api_bookmark_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Bookmark).filter_by(user_id=user.id, post_id=post_id).first()
        if not existing:
            s.add(Bookmark(user_id=user.id, post_id=post_id))
            s.commit()
    return {"ok": True}


@router.post("/posts/{post_id}/unbookmark")
def api_unbookmark_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(Bookmark).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            s.delete(existing)
            s.commit()
    return {"ok": True}


@router.get("/bookmarks")
def api_bookmarks(request: Request, limit: int = Query(20), offset: int = Query(0)):
    user = require_active_auth(request)
    with get_session() as s:
        raw = s.query(Bookmark).filter_by(user_id=user.id).order_by(desc(Bookmark.created_at)).offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        posts = [_post_json(b.post, s, user) for b in raw[:limit] if b.post and not b.post.is_deleted]
        return {"posts": posts, "has_more": has_more}


@router.get("/favorites")
def api_favorites(request: Request, limit: int = Query(10), offset: int = Query(0)):
    user = require_active_auth(request)
    with get_session() as s:
        raw = s.query(Like).filter_by(user_id=user.id).order_by(desc(Like.created_at)).offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        posts = [_post_json(l.post, s, user) for l in raw[:limit] if l.post and not l.post.is_deleted]
        return {"posts": posts, "has_more": has_more}


@router.post("/posts/{post_id}/unboost")
def api_unboost_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
        announce_id = existing.ap_id if existing and existing.ap_id else ""
        if existing:
            s.delete(existing)
            s.query(Notification).filter_by(
                from_user_id=user.id, notification_type="boost", post_id=post_id
            ).delete()
            remaining = s.query(Boost).filter_by(post_id=post_id).count()
            if remaining == 0:
                post.bumped_at = None
            s.commit()
            broadcast_refresh_notifs()
        if post.author and post.author.is_remote and post.author.shared_inbox_url:
            undo = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/boosts/{uuid.uuid4()}#undo",
                "type": "Undo",
                "actor": user.actor_uri(),
                "object": {
                    "id": announce_id or f"{BASE_URL}/boosts/{uuid.uuid4()}",
                    "type": "Announce",
                    "actor": user.actor_uri(),
                    "object": post.ap_id,
                },
            }
            inbox = post.author.shared_inbox_url
            try:
                _post_to_inbox(inbox, undo, user)
            except Exception:
                pass
    return {"ok": True}


@router.post("/posts/{post_id}/react")
def api_react_post(request: Request, post_id: int, emoji: str = Form(...)):
    user = require_active_auth(request)
    with get_session() as s:
        settings = ServerSetting.get(s)
        if not emoji or len(emoji) > 50:
            raise HTTPException(status_code=400, detail="Invalid emoji")
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        reactions_disabled = not settings.enable_reactions or not getattr(post.author, 'enable_reactions', True)
        final_emoji = emoji if not reactions_disabled else None
        existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        is_new = False
        if existing:
            existing.reaction = final_emoji
        else:
            s.add(Like(user_id=user.id, post_id=post_id, reaction=final_emoji))
            if post.author_id != user.id:
                s.add(Notification(user_id=post.author_id, from_user_id=user.id, notification_type="like", post_id=post_id))
            is_new = True
        s.commit()
        if post.author_id != user.id:
            from app.timeline_stream import broadcast_refresh_notifs
            broadcast_refresh_notifs()
        if post.author.is_remote and post.author.shared_inbox_url:
            from app.activitypub import _post_to_inbox
            like_activity = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/likes/{uuid.uuid4()}",
                "type": "Like",
                "actor": user.actor_uri(),
                "object": post.ap_id,
                "_misskey_reaction": emoji,
            }
            if is_new or (existing and existing.reaction != emoji):
                inbox = post.author.shared_inbox_url
                try:
                    _post_to_inbox(inbox, like_activity, user)
                except Exception:
                    pass
    return {"ok": True}


@router.post("/posts/{post_id}/unreact")
def api_unreact_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            s.delete(existing)
            s.query(Notification).filter_by(
                from_user_id=user.id, notification_type="like", post_id=post_id
            ).delete()
            s.commit()
            broadcast_refresh_notifs()
            if post.author.is_remote and post.author.shared_inbox_url:
                from app.activitypub import _post_to_inbox
                undo = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/likes/{uuid.uuid4()}#undo",
                    "type": "Undo",
                    "actor": user.actor_uri(),
                    "object": {
                        "id": f"{BASE_URL}/likes/{uuid.uuid4()}",
                        "type": "Like",
                        "actor": user.actor_uri(),
                        "object": post.ap_id,
                    },
                }
                try:
                    _post_to_inbox(post.author.shared_inbox_url, undo, user)
                except Exception:
                    pass
    return {"ok": True}


@router.post("/posts/{post_id}/vote")
def api_vote_post(request: Request, post_id: int, option: int = Form(...)):
    user = require_active_auth(request)
    remote_vote_data = None
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        options = post.poll_data.get("options", [])
        if option < 0 or option >= len(options):
            raise HTTPException(status_code=400, detail="Invalid option")
        expires_at = post.poll_data.get("expires_at")
        if expires_at:
            try:
                if datetime.datetime.fromisoformat(expires_at) < datetime.datetime.now(datetime.timezone.utc):
                    raise HTTPException(status_code=400, detail="Poll has ended")
            except (ValueError, TypeError):
                pass
        existing = s.query(Vote).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            old_option = existing.option_index
            if old_option == option:
                return {"ok": True}
            existing.option_index = option
        else:
            s.add(Vote(user_id=user.id, post_id=post_id, option_index=option))
        s.flush()
        votes = s.query(Vote.option_index, func.count(Vote.id).label("cnt")).filter(Vote.post_id == post_id).group_by(Vote.option_index).all()
        counts = {v.option_index: v.cnt for v in votes}
        for i, opt in enumerate(options):
            opt["votes_count"] = counts.get(i, 0)
        s.query(Post).filter(Post.id == post_id).update({"poll_data": {**post.poll_data, "options": options}}, synchronize_session=False)
        s.flush()
        s.refresh(post)
        post_json = _post_json(post, s, user)
        if post.ap_id and post.author and post.author.is_remote:
            inbox = post.author.shared_inbox_url or post.author.inbox_url
            if inbox:
                remote_vote_data = (post.ap_id, post.author.actor_uri(), inbox, options[option]["text"])
        s.commit()
    if remote_vote_data:
        from uuid import uuid4
        ap_id, author_uri, inbox, option_text = remote_vote_data
        vote_activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{BASE_URL}/votes/{uuid4()}/activity",
            "type": "Create",
            "actor": user.actor_uri(),
            "object": {
                "id": f"{BASE_URL}/votes/{uuid4()}",
                "type": "Note",
                "name": option_text,
                "attributedTo": user.actor_uri(),
                "to": [author_uri],
                "inReplyTo": ap_id,
            },
            "to": [author_uri],
        }
        try:
            _post_to_inbox(inbox, vote_activity, user)
        except Exception:
            pass
    return {"ok": True, "post": post_json}


@router.post("/posts/{post_id}/unvote")
def api_unvote_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        existing = s.query(Vote).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            options = post.poll_data.get("options", [])
            s.delete(existing)
            s.flush()
            votes = s.query(Vote.option_index, func.count(Vote.id).label("cnt")).filter(Vote.post_id == post_id).group_by(Vote.option_index).all()
            counts = {v.option_index: v.cnt for v in votes}
            for i, opt in enumerate(options):
                opt["votes_count"] = counts.get(i, 0)
            s.query(Post).filter(Post.id == post_id).update({"poll_data": {**post.poll_data, "options": options}}, synchronize_session=False)
            s.commit()
            s.expire_all()
    return {"ok": True}


@router.post("/pin/post/{post_id}")
def api_pin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post or post.author_id != user.id:
            raise HTTPException(status_code=404, detail="Post not found")
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            return {"ok": True}
        if len(pinned) >= 5:
            raise HTTPException(status_code=400, detail="최대 5개까지 고정할 수 있습니다.")
        pinned.append(post_id)
        s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
        s.commit()
    return {"ok": True}


@router.post("/unpin/post/{post_id}")
def api_unpin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            pinned.remove(post_id)
            s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
            s.commit()
    return {"ok": True}


@router.post("/pin/series/{novel_id}")
def api_pin_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        from app.models import Novel
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
    with get_session() as s:
        profile = s.query(User).filter_by(username=username).first()
        if "@" in username:
            parts = username.split("@")
            if len(parts) == 2:
                remote_user, remote_domain = parts
                actor_url = f"https://{remote_domain}/@{remote_user}"
                from app.activitypub import _resolve_actor
                _resolve_actor(actor_url)
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
        from sqlalchemy import select
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
        followers = s.query(Follow).filter_by(following_id=profile.id, accepted=True).all()
        following = s.query(Follow).filter_by(follower_id=profile.id, accepted=True).all()
        return {
            "profile": _user_json(profile),
            "posts": [_post_json(p, s, user) for p in posts],
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
            "pinned_posts_data": [_post_json(p, s, user) for p in (s.query(Post).filter(Post.id.in_(profile.pinned_posts or []), Post.is_deleted == False).all() if profile.pinned_posts else [])],
            "pinned_series_data": [_novel_json(n, s) for n in (s.query(Novel).filter(Novel.id.in_(profile.pinned_series or [])).all() if profile.pinned_series else [])],
        }


@router.get("/users/{username}/media")
def api_user_media(request: Request, username: str, limit: int = Query(12), offset: int = Query(0)):
    user = get_current_user(request)
    with get_session() as s:
        profile = s.query(User).filter_by(username=username).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        import json as _json
        raw = s.query(Post).options(
            selectinload(Post.author)
        ).filter(
            Post.author_id == profile.id,
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).offset(offset).limit(limit + 1).all()
        raw = [p for p in raw if p.media_attachments and len(_json.loads(p.media_attachments) if isinstance(p.media_attachments, str) else (p.media_attachments or [])) > 0]
        has_more = len(raw) > limit
        posts = [_post_json(p, s, user) for p in raw[:limit] if _can_view(p, user, s)]
        return {"posts": posts, "has_more": has_more}


@router.post("/users/{username}/follow")
def api_follow(request: Request, username: str):
    user = require_active_auth(request)
    if "@" in username and not username.startswith("@"):
        from app.activitypub import _resolve_actor, _post_to_inbox
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
                remote_obj = target.remote_url or target.actor_uri()
                follow_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{user.actor_uri()}#follows/{target.id}",
                    "type": "Follow",
                    "actor": user.actor_uri(),
                    "object": remote_obj,
                }
                s.add(Follow(follower_id=user.id, following_id=target.id, accepted=False, activity_id=follow_activity["id"]))
                s.commit()
                inbox = target.inbox_url or target.inbox_uri()
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
            broadcast_refresh_notifs()
            from app.push import send_push_to_user
            send_push_to_user(target.id, "follow" if accepted else "follow_request", user.username)
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
            from app.activitypub import _send_accept
            try:
                follow_activity_id = target.activity_id or f"{follower.actor_uri()}#follows/{user.id}"
                inbox = follower.inbox_url or (follower.actor_uri().rstrip("/") + "/inbox")
                _send_accept(inbox, follow_activity_id, user, follower=follower)
            except Exception as e:
                logger.warning("Failed to send Accept: %s", e)
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
        if follower_is_remote and follower:
            from app.activitypub import _send_reject
            try:
                follow_activity_id = f"{follower.actor_uri()}#follows/{user.id}"
                inbox = follower.inbox_url or (follower.actor_uri().rstrip("/") + "/inbox")
                _send_reject(inbox, follow_activity_id, user, follower_actor_url=follower.actor_uri())
            except Exception as e:
                logger.warning("Failed to send Reject: %s", e)
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
            if target.is_remote and target.inbox_uri():
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
                    _post_to_inbox(target.inbox_uri(), undo, user)
                except Exception as e:
                    logger.warning("Failed to send Undo Follow: %s", e)
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
        follows = s.query(Follow).filter_by(following_id=target.id, accepted=True).all()
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
        follows = s.query(Follow).filter_by(follower_id=target.id, accepted=True).all()
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
        if is_self:
            conv_posts = s.query(Post).options(selectinload(Post.author)).filter(
                Post.visibility == "mention",
                Post.is_deleted == False,
                Post.author_id == user.id,
                Post.mentioned_user_ids.contains(user.id),
            ).order_by(Post.created_at).all()
        else:
            conv_posts = s.query(Post).options(selectinload(Post.author)).filter(
                Post.visibility == "mention",
                Post.is_deleted == False,
                or_(
                    and_(
                        Post.author_id == user.id,
                        Post.mentioned_user_ids.contains(other_id),
                    ),
                    and_(
                        Post.author_id == other_id,
                        Post.mentioned_user_ids.contains(user.id),
                    ),
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
    three_months_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=90)
    with get_session() as s:
        from sqlalchemy import cast, String as SAString
        posts = s.query(Post).filter(
            Post.visibility == "mention",
            Post.is_deleted == False,
            Post.created_at >= three_months_ago,
            or_(
                Post.author_id == user.id,
                cast(Post.mentioned_user_ids, SAString).contains(str(user.id)),
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
            sorted_msgs = sorted(data["all_msgs"], key=lambda x: x.created_at or datetime.datetime.min, reverse=True)
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
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    candidates = []
    voted_posts = (
        session.query(Post)
        .join(Vote, Vote.post_id == Post.id)
        .filter(Vote.user_id == user_id, Post.poll_data.isnot(None), Post.is_deleted == False)
        .all()
    )
    candidates.extend(voted_posts)
    authored_posts = (
        session.query(Post)
        .filter(Post.author_id == user_id, Post.poll_data.isnot(None), Post.is_deleted == False)
        .all()
    )
    for p in authored_posts:
        if p not in candidates:
            candidates.append(p)
    for post in candidates:
        expires_at = post.poll_data.get("expires_at") if post.poll_data else None
        if not expires_at:
            continue
        try:
            exp = _dt.datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_dt.timezone.utc)
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
            import json as _json
            session.add(Notification(
                user_id=user_id,
                from_user_id=post.author_id,
                notification_type="poll_ended",
                post_id=post.id,
                metadata_json=_json.dumps({"is_author": post.author_id == user_id}),
            ))
    session.commit()


@router.get("/notifications")
def api_notifications(request: Request, filter_type: str = Query(""), limit: int = Query(20), offset: int = Query(0), mark_read: bool = Query(True)):
    user = require_auth(request)
    with get_session() as s:
        _generate_poll_end_notifications(user.id, s)
        q = s.query(Notification).filter_by(user_id=user.id)
        if filter_type == "follow":
            q = q.filter(Notification.notification_type.in_(["follow", "follow_request"]))
        elif filter_type == "vote":
            q = q.filter(Notification.notification_type.in_(["vote", "poll_ended"]))
        elif filter_type:
            q = q.filter_by(notification_type=filter_type)
        q = q.order_by(desc(Notification.created_at))
        total = q.count()
        raw = q.offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        notifs = raw[:limit]

        result = []
        for n in notifs:
            from_user = s.query(User).get(n.from_user_id) if n.from_user_id else None
            post = s.query(Post).get(n.post_id) if n.post_id else None
            import json as _json
            meta = {}
            if n.metadata_json:
                try: meta = _json.loads(n.metadata_json)
                except: pass
            item = {
                "id": n.id,
                "type": n.notification_type,
                "created_at": _fmt_dt(n.created_at),
                "is_read": n.is_read,
                "from_user": _user_json(from_user) if from_user else None,
                "post": _post_json(post, s, user) if post and not post.is_deleted and _can_view(post, user, s) else None,
                "metadata": meta,
            }
            result.append(item)

        # mark as read (only first page, when mark_read=true)
        if offset == 0 and mark_read:
            s.query(Notification).filter_by(user_id=user.id, is_read=False).update({"is_read": True})
            s.commit()

    return {"notifications": result, "has_more": has_more, "total": total}


@router.get("/notifications/stream")
async def api_notifications_stream(request: Request):
    user = require_auth(request)
    sid, q = add_notif_stream()
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


def _sync_tags(n, s):
    raw = n.tags or ""
    desired = set(t for t in raw.replace(",", " ").split() if t)
    current = {t.name for t in (n.tag_list or [])}
    for name in desired - current:
        tag = s.query(Tag).filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            s.add(tag)
            s.flush()
        n.tag_list.append(tag)
    for name in current - desired:
        tag = next(t for t in n.tag_list if t.name == name)
        n.tag_list.remove(tag)


def _novel_json(n, s=None):
    author = None
    if hasattr(n, 'author') and n.author:
        author = _user_json(n.author)
    tag_names = " ".join(t.name for t in (n.tag_list or [])) or (n.tags or "")
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
    if s is not None:
        result["followers_count"] = s.query(SeriesFollow).filter_by(novel_id=n.id).count()
    return result


@router.post("/series/new")
def api_create_novel(request: Request, title: str = Form(...), description: str = Form(""),
                     tags: str = Form(""), visibility: str = Form("public"), status: str = Form("ongoing"),
                     cover_image: UploadFile = File(None), is_sensitive: bool = Form(False)):
    user = require_active_auth(request)
    if getattr(user, 'is_deceased', False):
        raise HTTPException(status_code=403, detail="고인 계정은 시리즈를 생성할 수 없습니다.")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    from app.utils.storage import get_storage
    storage = get_storage()
    cover_url = ""
    if cover_image and cover_image.filename:
        from uuid import uuid4
        from PIL import Image as PILImage
        import io
        ext = "webp"
        ct = cover_image.content_type or ""
        if "gif" in ct:
            ext = "gif"
        key = f"series/covers/{uuid4().hex[:16]}.{ext}"
        img = PILImage.open(cover_image.file)
        target_w, target_h = 120, 160
        img_w, img_h = img.size
        ratio = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * ratio)
        new_h = int(img_h * ratio)
        img = img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
        if img.mode in ("RGBA", "P"):
            bg = PILImage.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        out = io.BytesIO()
        img.save(out, format="WEBP" if ext != "gif" else "GIF", quality=90)
        cover_url = storage.save(key, out.getvalue(), f"image/{ext}")
    with get_session() as s:
        import secrets
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
        episode_list = [_episode_json(e) for e in episodes]
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
    from app.utils.storage import get_storage
    storage = get_storage()
    cover_url = ""
    if cover_image and cover_image.filename:
        from uuid import uuid4
        from PIL import Image as PILImage
        import io
        ext = "webp"
        ct = cover_image.content_type or ""
        if "gif" in ct:
            ext = "gif"
        key = f"series/covers/{uuid4().hex[:16]}.{ext}"
        img = PILImage.open(cover_image.file)
        target_w, target_h = 120, 160
        img_w, img_h = img.size
        ratio = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * ratio)
        new_h = int(img_h * ratio)
        img = img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
        if img.mode in ("RGBA", "P"):
            bg = PILImage.new("RGB", img.size, (255, 255, 255))
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
            import secrets
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
                    "object": post.to_ap_note(),
                }
                s.commit()
                if visibility == "mention":
                    if post.mentioned_user_ids:
                        mu_users = s.query(User).filter(User.id.in_(post.mentioned_user_ids), User.is_remote == True).all()
                        for mu in mu_users:
                            _post_to_inbox(mu.inbox_uri(), create_activity, user)
                else:
                    broadcast_to_followers(user, create_activity)
            except Exception as e:
                logger.warning("Failed to broadcast episode federation: %s", e)
                s.commit()
        else:
            s.commit()

        # Notify series followers
        import json
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
            from app.push import send_push_to_user
            for sf in followers:
                if sf.user_id != user.id:
                    send_push_to_user(sf.user_id, "new_episode", user.username, metadata={"novel_id": novel.id})

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
            from datetime import datetime, timedelta
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
            import secrets
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
                    "object": post.to_ap_note(),
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
        s.delete(novel)
        s.commit()
    return {"ok": True}


def _episode_json(e):
    return {
        "id": e.id,
        "novel_id": e.novel_id,
        "episode_number": e.episode_number,
        "title": e.title,
        "content": e.content,
        "summary": e.summary or "",
        "comment": e.comment or "",
        "views": e.views or 0,
        "is_published": e.is_published,
        "created_at": _fmt_dt(e.created_at),
        "updated_at": _fmt_dt(e.updated_at),
    }


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
    import time
    from app.utils.storage import get_storage
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
                        enable_reactions: bool = Form(True)):
    user = require_auth(request)
    valid_post = ("public", "home", "followers", "mention")
    if default_visibility not in valid_post:
        default_visibility = "public"
    if episode_default_visibility not in valid_post:
        episode_default_visibility = "public"
    if follow_list_visibility not in ("public", "private"):
        follow_list_visibility = "public"
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        db.default_visibility = default_visibility
        db.episode_default_visibility = episode_default_visibility
        db.is_locked = is_locked
        db.is_bot = is_bot
        db.follow_list_visibility = follow_list_visibility
        db.enable_reactions = enable_reactions
        if user.role in ("admin", "moderator", "owner"):
            db.show_badge = show_badge
        s.commit()
    return {"ok": True}


@router.post("/settings/change-email")
def api_settings_change_email(request: Request, email: str = Form(...)):
    user = require_auth(request)
    import re
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
    from app.utils.storage import get_storage
    storage = get_storage()
    from PIL import Image as PILImage
    import io, os
    ext = os.path.splitext(file.filename or "file")[1].lower() if file.filename else ""
    is_video = ext in (".mp4", ".webm", ".ogg", ".mov")
    is_image = ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico")
    if not is_image and not is_video:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    if is_video:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=400, detail="Video exceeds maximum size (25MB)")
    from uuid import uuid4
    name = f"{uuid4().hex}.webp" if is_image else f"{uuid4().hex}{ext}"
    key = f"media/{name}"
    if is_image:
        img = PILImage.open(io.BytesIO(file.file.read()))
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
    from app.routes.auth import hash_password, verify_password
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

        import json as _json
        try:
            sids = _json.loads(series_ids)
            if not isinstance(sids, list):
                sids = []
        except (_json.JSONDecodeError, TypeError):
            sids = []

        # Notify target user for approval
        meta = _json.dumps({
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
    import json as _json
    try:
        parsed = _json.loads(aliases)
        if not isinstance(parsed, list):
            parsed = []
    except (_json.JSONDecodeError, TypeError):
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


def _domain_from_actor(u) -> str:
    if not u:
        return ""
    if u.is_remote and u.remote_url:
        from urllib.parse import urlparse
        return urlparse(u.remote_url).hostname or ""
    from app.config import DOMAIN
    return DOMAIN


@router.get("/settings/export/{export_type}")
def api_export_account(request: Request, export_type: str):
    user = require_auth(request)
    import csv, io
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
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={export_type}.csv"})


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
    from PIL import Image as PILImage
    import io
    from uuid import uuid4
    key = f"{prefix}/local/u{user_id}_{uuid4().hex[:8]}.webp"
    img = PILImage.open(file.file)
    img.thumbnail(max_size, PILImage.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        bg = PILImage.new("RGB", img.size, (255, 255, 255))
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
    from app.utils.storage import get_storage
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
        import json
        try:
            parsed_fields = json.loads(custom_fields)
            if isinstance(parsed_fields, list):
                db.custom_fields = parsed_fields
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


@router.get("/by-series-number/{username}/{number}")
def api_by_series_number(request: Request, username: str, number: str):
    user = get_current_user(request)
    with get_session() as s:
        author = s.query(User).filter_by(username=username).first()
        if not author:
            raise HTTPException(status_code=404, detail="User not found")
        novel = s.query(Novel).filter_by(author_id=author.id, number=number).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if novel.visibility == "private" and (not user or novel.author_id != user.id):
            raise HTTPException(status_code=404, detail="Novel not found")
        return {"id": novel.id}


@router.post("/fetch-series")
def api_fetch_series(request: Request, url: str = Form(...)):
    user = get_current_user(request)
    with get_session() as s:
        import re
        m = re.match(r"https?://[^/]+/series/(\d+)", url)
        if m:
            novel = s.query(Novel).filter_by(id=int(m.group(1))).first()
            if novel and novel.visibility != "private":
                author = s.query(User).get(novel.author_id)
                return {"type": "series", "novel": _novel_json(novel, s), "author": _user_json(author) if author else None}
        m = re.match(r"https?://[^/]+/series/by-number/(\w+)/([a-f0-9]+)", url)
        if m:
            author = s.query(User).filter_by(username=m.group(1)).first()
            if author:
                novel = s.query(Novel).filter_by(author_id=author.id, number=m.group(2)).first()
                if novel and novel.visibility != "private":
                    return {"type": "series", "novel": _novel_json(novel, s), "author": _user_json(author)}
        raise HTTPException(status_code=404, detail="Series not found")


@router.post("/fetch-episode")
def api_fetch_episode(request: Request, url: str = Form(...)):
    user = get_current_user(request)
    with get_session() as s:
        import re
        m = re.match(r"https?://[^/]+/series/(\d+)/episodes/(\d+)", url)
        if m:
            novel = s.query(Novel).filter_by(id=int(m.group(1))).first()
            if not novel or novel.visibility == "private":
                raise HTTPException(status_code=404, detail="Episode not found")
            episode = s.query(Episode).filter_by(id=int(m.group(2)), novel_id=novel.id).first()
            if not episode or not episode.is_published:
                raise HTTPException(status_code=404, detail="Episode not found")
            author = s.query(User).get(novel.author_id)
            return {
                "type": "episode",
                "episode": _episode_json(episode),
                "novel": _novel_json(novel, s),
                "author": _user_json(author) if author else None,
            }
        raise HTTPException(status_code=404, detail="Episode not found")


@router.get("/by-number/{username}/{number}")
def api_by_number(request: Request, username: str, number: str):
    accept = request.headers.get("accept", "")
    with get_session() as s:
        author = s.query(User).filter_by(username=username).first()
        if not author:
            raise HTTPException(status_code=404, detail="User not found")
        post = s.query(Post).filter_by(author_id=author.id, number=number).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        # ActivityPub 요청 → AP JSON 반환
        if "application/activity+json" in accept or "application/ld+json" in accept:
            if post.visibility not in ("public", "unlisted", "home"):
                raise HTTPException(status_code=403, detail="Not authorized")
            return JSONResponse(content=post.to_ap_note(), media_type="application/activity+json")
        # 일반 요청 → 로그인 필요
        user = get_current_user(request)
        if not user:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        return _post_json(post, s, user)


@router.get("/explore")
def api_explore(request: Request):
    user = get_current_user(request)
    with get_session() as s:
        local_ids = [u.id for u in s.query(User).filter_by(is_remote=False).all()]
        posts = s.query(Post).options(
            selectinload(Post.author)
        ).filter(
            Post.author_id.in_(local_ids),
            Post.visibility == "public",
            Post.is_deleted == False,
            Post.in_reply_to_id == None,
        ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).limit(30).all()

        novels = _apply_latest_activity_order(s.query(Novel).options(
            selectinload(Novel.author),
            selectinload(Novel.tag_list),
        ).filter(
            Novel.visibility == "public",
            Novel.is_published == True,
        ), s).limit(20).all()

        return {
            "posts": [_post_json(p, s, user) for p in posts],
            "novels": [_novel_json(n, s) for n in novels],
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
                from app.models import ServerSetting, FederationBlock, AllowedServer
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
        if is_hashtag_search:
            tag = s.query(Tag).filter_by(name=query.lower()).first()
            if tag:
                q_posts = s.query(Post).options(selectinload(Post.author)).filter(
                    Post.tag_list.any(id=tag.id),
                    Post.is_deleted == False,
                )
                if user:
                    q_posts = q_posts.filter(
                        or_(Post.visibility == "public", Post.author_id == user.id)
                    )
                else:
                    q_posts = q_posts.filter(Post.visibility == "public")
                if author:
                    author_user = s.query(User).filter_by(username=author).first()
                    if author_user:
                        q_posts = q_posts.filter(Post.author_id == author_user.id)
                posts = q_posts.order_by(desc(Post.created_at)).limit(20).all()
            else:
                posts = []
            novels = []
        else:
            posts = s.query(Post).options(selectinload(Post.author)).filter(
                Post.content.ilike(pattern),
                Post.visibility == "public",
                Post.is_deleted == False,
                Post.in_reply_to_id == None,
            ).order_by(desc(Post.created_at)).limit(20).all()
            novels = _apply_latest_activity_order(s.query(Novel).options(selectinload(Novel.author)).filter(
                or_(Novel.title.ilike(pattern), Novel.description.ilike(pattern)),
                Novel.is_published == True,
                Novel.visibility == "public",
            ), s).limit(20).all()
        local_users = s.query(User).filter(
            User.is_remote == False,
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern)),
        ).limit(20).all()
        remote_users = s.query(User).filter(
            User.is_remote == True,
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
                        import httpx
                        from app.activitypub import _resolve_actor
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

    # First, recursively fetch parent posts if this is a reply
    in_reply_to = obj.get("inReplyTo", "")
    if isinstance(in_reply_to, dict):
        in_reply_to = in_reply_to.get("id", "")
    if in_reply_to and in_reply_to not in _visited:
        _visited.add(in_reply_to)
        parent_data = _ap_fetch(in_reply_to, user)
        if parent_data:
            parent_obj = parent_data.get("object", parent_data)
            _fetch_and_save_ap_object(parent_obj, user, _visited, _depth + 1)

    from app.activitypub import _sanitize_html, _normalize_mentions
    content = _normalize_mentions(_sanitize_html(obj.get("content", "")))
    if not content:
        return None

    attributed_to = obj.get("attributedTo", "")
    if isinstance(attributed_to, list):
        attributed_to = attributed_to[0] if attributed_to else ""
    if not attributed_to:
        return None

    from app.activitypub import _resolve_actor
    _resolve_actor(attributed_to)
    author_id = None
    with get_session() as qs:
        u = qs.query(User).filter_by(remote_url=attributed_to).first()
        if u:
            author_id = u.id
    if not author_id:
        # fallback: try parsing username from attributed_to URL
        try:
            from urllib.parse import urlparse
            parsed = urlparse(attributed_to)
            domain = parsed.netloc
            preferred = parsed.path.rstrip("/").split("/")[-1]
            local_username = f"{preferred}@{domain}"
            with get_session() as qs:
                u = qs.query(User).filter_by(username=local_username).first()
                if u:
                    u.remote_url = attributed_to
                    qs.commit()
                    author_id = u.id
        except Exception:
            pass
    if not author_id:
        return None

    ap_id = obj.get("id", "")
    summary = obj.get("summary", "")

    # Process custom emoji tags before saving
    with get_session() as emoji_session:
        _process_emoji_tags(obj.get("tag", []), emoji_session)
        emoji_session.commit()

    with get_session() as s:
        existing = s.query(Post).filter_by(ap_id=ap_id).first()
        if existing and not existing.is_deleted:
            return _post_json(existing, s, user)
        if existing and existing.is_deleted:
            existing.is_deleted = False
            existing.content = content
            existing.summary = summary
            s.commit()
            return _post_json(existing, s, user)

        import re
        mentioned_names = set(re.findall(r'@(\w+(?:@[\w.-]+)?)', content or ""))
        mentioned_ids = []
        if mentioned_names:
            mentioned = s.query(User).filter(User.username.in_(mentioned_names)).all()
            mentioned_ids = [u.id for u in mentioned]

        in_reply_to_ap_id = obj.get("inReplyTo", "")

        in_reply_to_id = None
        if in_reply_to_ap_id:
            parent = s.query(Post).filter_by(ap_id=in_reply_to_ap_id).first()
            if parent:
                in_reply_to_id = parent.id

        # Determine visibility from to/cc like _handle_create
        to = obj.get("to", [])
        if isinstance(to, str): to = [to]
        cc = obj.get("cc", [])
        if isinstance(cc, str): cc = [cc]
        all_auds = to + cc
        pub = "https://www.w3.org/ns/activitystreams#Public"
        if pub in to:
            vis = "public"
        elif pub in cc:
            vis = "home"
        elif any(a.endswith("/followers") for a in all_auds):
            vis = "followers"
        elif all(a.startswith("http") for a in all_auds if a):
            vis = "mention"
        else:
            vis = "home"

        post = Post(
            author_id=author_id,
            content=content,
            summary=summary,
            visibility=vis,
            ap_id=ap_id,
            in_reply_to_ap_id=in_reply_to_ap_id,
            in_reply_to_id=in_reply_to_id,
            mentioned_user_ids=mentioned_ids,
        )
        published = obj.get("published", "")
        if published:
            try:
                post.created_at = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))
            except Exception as e:
                logger.warning("Failed to parse published date: %s", e)
        s.add(post)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            s.close()
            with get_session() as s2:
                existing = s2.query(Post).filter_by(ap_id=ap_id).first()
                if existing:
                    return _post_json(existing, s2, user)
            return None
        return _post_json(post, s, user)


def _safe_httpx_get(url, headers=None, timeout=15, max_size=5*1024*1024):
    """HTTP GET with redirect validation and size limit."""
    import httpx
    from app.activitypub import _validate_url
    if not _validate_url(url):
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
    from app.activitypub import _validate_url
    from urllib.parse import urlparse
    import datetime, time

    if not _validate_url(url):
        return None

    from app.crypto_utils import sign_string

    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    parsed = urlparse(url)
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

    resp = _safe_httpx_get(url, headers=headers)
    if not resp or resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None

@router.get("/notifications/unread-count")
def api_unread_count(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        count = s.query(Notification).filter_by(user_id=user.id, is_read=False).count()
    return {"count": count}


def _check_fetch_domain_allowed(url: str) -> str | None:
    """Return an error message if the URL's domain is federated-blocked, else None."""
    from urllib.parse import urlparse
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


@router.post("/fetch-actor")
def api_fetch_actor(request: Request, url: str = Form(...)):
    import sys
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    err = _check_fetch_domain_allowed(url)
    if err:
        raise HTTPException(status_code=403, detail=err)
    from app.activitypub import _resolve_actor, _safe_fetch
    from app.activitypub import _safe_fetch
    actor = _resolve_actor(url, force_refresh=True, sign_as=user)
    if not actor:
        raise HTTPException(status_code=400, detail="Cannot resolve actor")

    # Fetch recent posts from outbox (re-fetch actor to get outbox URL)
    outbox_url = None
    try:
        import datetime, time
        from app.crypto_utils import sign_string, get_private_key
        from urllib.parse import urlparse
        date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        parsed = urlparse(url)
        created = int(time.time())
        ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
        priv = get_private_key(user, SECRET_KEY)
        sig = sign_string(ss, priv)
        sig_header = f'keyId="{user.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
        headers = {"Accept": "application/activity+json", "Signature": sig_header, "Date": date, "Host": parsed.netloc}
        r = _safe_httpx_get(url, headers=headers)
        if r:
            ap_data = r.json()
            outbox_url = ap_data.get("outbox", "")
    except Exception:
        pass

    if outbox_url:
        try:
            import datetime, time
            parsed2 = urlparse(outbox_url)
            date2 = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
            created2 = int(time.time())
            path2 = parsed2.path or "/"
            if parsed2.query:
                path2 += f"?{parsed2.query}"
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
    return _user_json(actor)


@router.post("/fetch-post")
def api_fetch_post(request: Request, url: str = Form(...)):
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    err = _check_fetch_domain_allowed(url)
    if err:
        raise HTTPException(status_code=403, detail=err)

    data = _ap_fetch(url, user)
    if not data:
        raise HTTPException(status_code=400, detail="Cannot fetch post")

    obj = data.get("object", data)
    obj_type = data.get("type", obj.get("type", ""))
    if obj_type not in ("Note", "Article"):
        raise HTTPException(status_code=400, detail=f"Not a Note/Article (type={obj_type})")

    result = _fetch_and_save_ap_object(obj, user)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to save post")
    # Include emoji data so frontend can render immediately
    emojis = []
    with get_session() as es:
        for e in es.query(CustomEmoji).order_by(CustomEmoji.keyword).all():
            emojis.append({"keyword": e.keyword, "file_name": e.file_name, "url": _emoji_url(e.file_name), "aliases": e.aliases or []})
    result["_emojis"] = emojis
    return result


EMOJI_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "emojis")

def _emoji_url(file_name: str) -> str:
    """Return the correct emoji URL (local or S3)."""
    from app.config import S3_ENABLED
    if S3_ENABLED:
        from app.utils.storage import get_storage
        try:
            storage = get_storage()
            return storage.url(f"emojis/{file_name}")
        except Exception:
            pass
    return f"/emojis/{file_name}"


@router.get("/emojis")
def api_list_emojis():
    with get_session() as s:
        emojis = s.query(CustomEmoji).order_by(CustomEmoji.keyword).all()
        return [
            {
                "id": e.id,
                "keyword": e.keyword,
                "file_name": e.file_name,
                "category": e.category or "",
                "aliases": e.aliases or [],
                "url": _emoji_url(e.file_name),
                "source_url": e.source_url or "",
                "domain": e.domain or "",
            }
            for e in emojis
        ]


@router.post("/emojis")
def api_create_emoji(
    request: Request,
    keyword: str = Form(...),
    category: str = Form(""),
    aliases: str = Form(""),
    image: UploadFile = File(...),
):
    user = require_auth(request)
    if not keyword.strip():
        raise HTTPException(status_code=400, detail="Keyword is required")
    keyword = keyword.strip().lower().replace(" ", "_")
    if not re.match(r'^[a-z0-9_]+$', keyword):
        raise HTTPException(status_code=400, detail="Keyword must be lowercase alphanumeric with underscores")

    allowed_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if image.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {image.content_type}")

    import uuid
    ext = image.filename.rsplit(".", 1)[-1].lower() if image.filename else "png"
    file_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(EMOJI_DIR, file_name)

    try:
        from PIL import Image
        tmp = Image.open(image.file)
        w, h = tmp.size
        tmp.close()
        image.file.seek(0)
        if h > 0 and w / h > 1.5:
            raise HTTPException(status_code=400, detail="Emoji is too wide (max 2x height)")
        if ext == "gif":
            with open(file_path, "wb") as f:
                f.write(image.file.read())
        else:
            file_name = f"{uuid.uuid4().hex}.webp"
            file_path = os.path.join(EMOJI_DIR, file_name)
            img = Image.open(image.file)
            if img.mode == "RGBA" or img.mode == "P":
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            if img.width > 66 or img.height > 66:
                img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
            img.save(file_path, format="WEBP", quality=100)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process image: {e}")

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
        return {
            "id": emoji.id,
            "keyword": emoji.keyword,
            "file_name": emoji.file_name,
            "category": emoji.category or "",
            "aliases": emoji.aliases or [],
            "url": _emoji_url(emoji.file_name),
        }


@router.patch("/emojis/{emoji_id}")
def api_update_emoji(request: Request, emoji_id: int, category: str = Form(""), keyword: str = Form(""), aliases: str = Form("")):
    user = require_auth(request)
    with get_session() as s:
        emoji = s.query(CustomEmoji).get(emoji_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        if keyword:
            keyword_clean = keyword.strip().lower().replace(" ", "_").replace(":", "")
            existing = s.query(CustomEmoji).filter(CustomEmoji.keyword == keyword_clean, CustomEmoji.id != emoji_id).first()
            if existing:
                raise HTTPException(status_code=400, detail="Keyword already taken")
            emoji.keyword = keyword_clean
        if category:
            emoji.category = category
        if aliases:
            emoji.aliases = [a.strip().lower().replace(" ", "_") for a in aliases.split(",") if a.strip()]
        s.commit()
        return {"ok": True, "emoji": {"id": emoji.id, "keyword": emoji.keyword, "file_name": emoji.file_name, "category": emoji.category, "aliases": emoji.aliases or [], "url": _emoji_url(emoji.file_name), "source_url": emoji.source_url or "", "domain": emoji.domain or ""}}

@router.delete("/emojis/{emoji_id}")
def api_delete_emoji(request: Request, emoji_id: int):
    user = require_auth(request)
    with get_session() as s:
        emoji = s.query(CustomEmoji).get(emoji_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        from app.utils.storage import get_storage
        try:
            get_storage().delete(f"emojis/{emoji.file_name}")
        except Exception:
            pass
        file_path = os.path.join(EMOJI_DIR, emoji.file_name)
        if os.path.isfile(file_path):
            os.remove(file_path)
        s.delete(emoji)
        s.commit()
    return {"ok": True}


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
            from datetime import datetime, timedelta
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
    import json
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
    from app.routes.auth import hash_password
    import secrets
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
            for p in s.query(Post).filter(Post.author_id == u.id).all():
                s.query(Post).filter(Post.in_reply_to_id == p.id).update({"in_reply_to_id": None})
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
        import json
        notif = Notification(
            user_id=u.id,
            from_user_id=user.id,
            notification_type="moderation",
            metadata_json=json.dumps({"action": action, "message": message}, ensure_ascii=False),
        )
        s.add(notif)
        s.commit()
        log_admin_action(user.id, user.username, f"moderate:{action}", target_type="user", target_id=user_id, target_username=u.username, details=message or "", ip_address=request.client.host if request.client else "")

        if send_email and u.email:
            try:
                from email.mime.text import MIMEText
                import smtplib
                from app.config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
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


@router.get("/admin/content/search")
def api_admin_content_search(request: Request, q: str = "", mode: str = "series"):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not q.strip():
        return {"novels": [], "episodes": []}
    with get_session() as s:
        from sqlalchemy.orm import selectinload, joinedload
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

@router.post("/admin/novels/{novel_id}/toggle-sensitive")
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


@router.post("/admin/novels/{novel_id}/set-visibility")
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


@router.post("/admin/episodes/{episode_id}/toggle-publish")
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


@router.get("/admin/reports")
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


@router.get("/admin/reports/{report_id}")
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


@router.post("/admin/reports/{report_id}/resolve")
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


@router.post("/admin/reports/{report_id}/dismiss")
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


@router.post("/admin/reports/{report_id}/forward")
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
        from app.activitypub import _send_flag
        reporter = s.query(User).get(report.reporter_id)
        if not reporter:
            raise HTTPException(status_code=400, detail="Reporter not found")
        try:
            _send_flag(reporter, report.target_type, target_obj, report.reason[:200], report.rule_ids or [])
        except Exception as e:
            logger.error("Failed to forward report %s: %s", report_id, e)
            raise HTTPException(status_code=500, detail=f"Failed to forward: {e}")
    return {"ok": True}

@router.get("/admin/rules")
def api_admin_list_rules(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        rules = s.query(ServerRule).order_by(ServerRule.sort_order).all()
        return [{"id": r.id, "title": r.title, "description": r.description, "sort_order": r.sort_order} for r in rules]


@router.post("/admin/rules/new")
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


@router.post("/admin/rules/{rule_id}/edit")
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


@router.post("/admin/rules/{rule_id}/delete")
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


@router.post("/admin/rules/reorder")
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


@router.post("/admin/posts/{post_id}/set-cw")
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


@router.post("/admin/posts/{post_id}/remove-cw")
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


@router.get("/admin/blocked-domains")
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


@router.post("/admin/block-domain")
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


@router.delete("/admin/block-domain/{domain}")
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


@router.get("/admin/federation-blocks")
def api_admin_list_federation_blocks(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        blocks = s.query(FederationBlock).order_by(FederationBlock.created_at.desc()).all()
        return {"blocks": [{"id": b.id, "domain": b.domain, "reason": b.reason or "", "created_by": b.created_by.username if b.created_by else "", "created_at": str(b.created_at) if b.created_at else ""} for b in blocks]}


@router.post("/admin/federation-block")
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


@router.delete("/admin/federation-block/{domain}")
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


@router.get("/admin/allowed-servers")
def api_admin_list_allowed_servers(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        servers = s.query(AllowedServer).order_by(AllowedServer.created_at.desc()).all()
        return {"servers": [{"id": sv.id, "domain": sv.domain, "created_by": sv.created_by.username if sv.created_by else "", "created_at": str(sv.created_at) if sv.created_at else ""} for sv in servers]}


@router.post("/admin/allowed-server")
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


@router.delete("/admin/allowed-server/{domain}")
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


@router.get("/admin/remote-servers")
def api_admin_remote_servers(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        remote_users = s.query(User).filter(User.is_remote == True).all()
        domains = set()
        for u in remote_users:
            if u.remote_url:
                from urllib.parse import urlparse
                domain = urlparse(u.remote_url).hostname
                if domain:
                    domains.add(domain)
        return {"servers": sorted(domains)}


@router.get("/admin/remote-server/{domain:path}")
def api_admin_remote_server(domain: str, request: Request, offset: int = 0, limit: int = 20):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    from urllib.parse import urlparse
    with get_session() as s:
        from sqlalchemy import or_
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

        import httpx
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


@router.get("/admin/federation-search")
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
                    from urllib.parse import urlparse
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
                    import httpx
                    from app.activitypub import _resolve_actor
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


def _domain_users(s, domain):
    """Return all remote User objects whose remote_url hostname matches domain."""
    from urllib.parse import urlparse
    from sqlalchemy import or_
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


@router.post("/admin/remote-server/{domain:path}/block")
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


@router.post("/admin/remote-server/{domain:path}/unblock")
def api_admin_remote_server_unblock(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        s.query(FederationBlock).filter_by(domain=domain).delete()
        s.commit()
    log_admin_action(user.id, user.username, "federation_unblock", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/remote-server/{domain:path}/mute")
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


@router.post("/admin/remote-server/{domain:path}/unmute")
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


@router.post("/admin/remote-server/{domain:path}/media-mute")
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


@router.post("/admin/remote-server/{domain:path}/unmedia-mute")
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


@router.post("/admin/remote-server/{domain:path}/purge")
def api_admin_remote_server_purge(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    from app.utils.storage import get_storage
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
            import re as _re
            _esc = _re.escape(domain)
            _mention_re = _re.compile(
                r'<span class="h-card"[^>]*>'
                r'<a href="[^"]*' + _esc + r'[^"]*" class="u-url mention">'
                r'@<span>([^<]+)</span></a></span>'
            )
            _mention_re2 = _re.compile(
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


@router.post("/admin/federation-mode")
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


@router.get("/admin/federation-mode")
def api_admin_get_federation_mode(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        settings = ServerSetting.get(s)
        return {"mode": settings.federation_mode or "blacklist"}


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
    with get_session() as s:
        existing = s.query(UserBlock).filter_by(user_id=user.id, target_user_id=target_user_id).first()
        if existing:
            return {"ok": True}
        s.add(UserBlock(user_id=user.id, target_user_id=target_user_id))
        # Remove follows both ways
        s.query(Follow).filter_by(follower_id=user.id, following_id=target_user_id).delete()
        s.query(Follow).filter_by(follower_id=target_user_id, following_id=user.id).delete()
        s.commit()
    return {"ok": True}


@router.delete("/blocks/users/{target_user_id}")
def api_unblock_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(UserBlock).filter_by(user_id=user.id, target_user_id=target_user_id).delete()
        s.commit()
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
    import json
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
    import httpx, re as _re
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc
    result = {"url": url, "title": domain, "description": "", "image": ""}
    try:
        resp = httpx.get(url, headers={"User-Agent": "WRIT/1.0"}, timeout=10, follow_redirects=True)
        if resp.status_code == 200:
            html = resp.text
            def _og(n):
                m = _re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', html, _re.I)
                if not m:
                    m = _re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', html, _re.I)
                return m.group(1) if m else ""
            og_title = _og("title") or _re.search(r'<title>([^<]*)</title>', html, _re.I)
            result["title"] = (_og("title") or (og_title.group(1) if og_title else domain))[:200]
            result["description"] = (_og("description") or "")[:400]
            result["image"] = _og("image") or ""
            if result["image"] and result["image"].startswith("/"):
                result["image"] = f"{parsed.scheme}://{parsed.netloc}{result['image']}"
    except Exception:
        pass
    return result


@router.get("/server-info")
def api_server_info():
    with get_session() as s:
        from app.models import ServerSetting
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


@router.get("/admin/settings")
def api_admin_get_settings(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        from app.models import ServerSetting
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
        from app.models import ServerSetting
        from app.utils.storage import get_storage
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


def _read_storage_file(url: str) -> bytes:
    """Read file from storage by URL. Handles both /uploads/... and absolute URLs."""
    from app.utils.storage import get_storage
    storage = get_storage()
    if isinstance(storage, LocalStorage):
        key = storage._extract_path(url)
        if key and os.path.isfile(key):
            with open(key, "rb") as f:
                return f.read()
    try:
        if not url.startswith("http"):
            from app.config import BASE_URL
            url = f"{BASE_URL}{url}"
        import httpx
        resp = httpx.get(url, timeout=10)
        if resp.is_success:
            return resp.content
    except Exception as e:
        logger.warning("Failed to read file via HTTP %s: %s", url, e)
    raise FileNotFoundError(url)


def _save_pwa_icons(source_url: str):
    if not source_url:
        return
    from PIL import Image
    from app.utils.storage import get_storage
    import io, os
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
    from PIL import Image
    from app.utils.storage import get_storage
    import io, os
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
    from app.utils.storage import get_storage
    try:
        get_storage().delete("pwa/favicon.png")
    except Exception:
        pass


def _delete_pwa_icons():
    """Remove PWA icons from storage, restoring default."""
    from app.utils.storage import get_storage
    storage = get_storage()
    for size in (192, 512):
        try:
            storage.delete(f"pwa/icon-{size}.png")
        except Exception:
            pass


@router.get("/pwa/manifest")
def api_pwa_manifest():
    from app.models import ServerSetting
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
    from fastapi.responses import Response, FileResponse
    from app.utils.storage import get_storage
    storage = get_storage()
    try:
        data = storage.get("pwa/favicon.png")
        if data:
            logger.info("[favicon] serving custom favicon (%d bytes)", len(data))
            return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-cache, max-age=0", "Vary": "Accept-Encoding"})
    except Exception as e:
        logger.info("[favicon] no custom favicon: %s", e)
    import os
    for path in [
        os.path.join(os.path.dirname(__file__), "..", "..", "static", "favicon.ico"),
        os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "favicon.ico"),
    ]:
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache, max-age=0"})
    return JSONResponse({"error": "Not found"}, status_code=404)


@router.get("/pwa/icon/{size}")
def api_pwa_icon(size: int):
    from fastapi.responses import Response, FileResponse
    from app.utils.storage import get_storage
    storage = get_storage()
    try:
        data = storage.get(f"pwa/icon-{size}.png")
        if data:
            from fastapi.responses import Response
            return Response(content=data, media_type="image/png")
    except Exception:
        pass
    # Fallback to default icon
    import os
    default_path = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "icons", f"icon-{size}.png")
    if os.path.exists(default_path):
        from fastapi.responses import FileResponse
        return FileResponse(default_path, media_type="image/png")
    return JSONResponse({"error": "Not found"}, status_code=404)


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
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ── Web Push ──

@router.get("/push/vapid-public-key")
def get_vapid_public_key():
    from app.config import VAPID_PUBLIC_KEY
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(404, "Web Push not configured")
    return {"publicKey": VAPID_PUBLIC_KEY}


@router.post("/push/subscribe")
def subscribe_push(request: Request, endpoint: str = Form(...), p256dh: str = Form(...), auth: str = Form(...)):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).first()
        if existing:
            existing.p256dh = p256dh
            existing.auth = auth
        else:
            s.add(PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth))
        s.commit()
    return {"ok": True}


@router.post("/push/unsubscribe")
def unsubscribe_push(request: Request, endpoint: str = Form(...)):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).delete()
        s.commit()
    return {"ok": True}


@router.get("/push/status")
def push_status(request: Request):
    user = require_active_auth(request)
    with get_session() as s:
        count = s.query(PushSubscription).filter_by(user_id=user.id).count()
    return {"subscribed": count > 0}

