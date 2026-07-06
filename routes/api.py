import os
import re
import datetime
import logging
from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy import desc, or_, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from models import User, Post, Follow, Like, Boost, Bookmark, Notification, Novel, Episode, Tag, CustomEmoji, get_session
from routes.auth import require_auth, get_current_user

KST = datetime.timezone(datetime.timedelta(hours=9))

def _fmt_dt(dt: datetime.datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(KST).isoformat()
from activitypub import broadcast_to_followers, _post_to_inbox, _process_emoji_tags
from config import BASE_URL, MAX_POST_LENGTH, SECRET_KEY
from crypto_utils import encrypt_key, get_private_key
from eventbus import broadcast
from utils.storage import LocalStorage

logger = logging.getLogger("writ.api")

router = APIRouter(prefix="/api")


# ── helpers ──

def _post_json(p, session, user):
    liked = session.query(Like).filter_by(user_id=user.id, post_id=p.id).first() is not None if user else False
    boosted = session.query(Boost).filter_by(user_id=user.id, post_id=p.id).first() is not None if user else False
    bookmarked = session.query(Bookmark).filter_by(user_id=user.id, post_id=p.id).first() is not None if user else False
    latest_boost = session.query(Boost).filter_by(post_id=p.id).order_by(desc(Boost.created_at)).first()
    booster = session.query(User).get(latest_boost.user_id) if latest_boost else None
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
        "ap_id": p.ap_id or "",
        "reply_context": _reply_context(p),
        "boosted_by": _user_json(booster) if booster and booster.id != p.author_id else None,
    }


def _user_json(u):
    role = getattr(u, 'role', 'user') or 'user'
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "avatar": u.profile_image or "",
        "summary": u.summary or "",
        "is_admin": u.is_admin,
        "is_locked": u.is_locked or False,
        "is_remote": u.is_remote,
        "role": role,
        "show_badge": getattr(u, 'show_badge', False) or False,
        "default_visibility": u.default_visibility or "public",
        "series_default_visibility": u.series_default_visibility or "public",
        "episode_default_visibility": u.episode_default_visibility or "public",
    }


def _reply_context(p):
    parent = p.parent if hasattr(p, 'parent') else None
    if not parent:
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
    mentioned = set(re.findall(r'@(\w+)', content))
    if not mentioned:
        return []
    with get_session() as s:
        users = s.query(User).filter(User.username.in_(mentioned)).all()
        return [u.id for u in users]


TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


# ── Auth API ──

@router.get("/auth/me")
def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return _user_json(user)


@router.post("/auth/login")
def api_login(request: Request, username: str = Form(...), password: str = Form(...)):
    from routes.auth import hash_password, verify_password, create_session
    with get_session() as s:
        db_user = s.query(User).filter_by(username=username, is_remote=False).first()
        if not db_user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        stored = db_user.password_hash
        if ":" not in stored:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        salt, hval = stored.split(":", 1)
        if not verify_password(password, salt, hval):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if getattr(db_user, 'is_suspended', False):
            raise HTTPException(status_code=403, detail="Account suspended")
        token = create_session(db_user.id)
        # Store IP
        client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0].strip()
        if client_ip:
            ips = db_user.recent_ips or []
            ips = [ip for ip in ips if ip != client_ip]  # remove duplicate
            ips.insert(0, client_ip)
            db_user.recent_ips = ips[:10]
            s.commit()
        resp = JSONResponse(_user_json(db_user))
        resp.set_cookie(key="session", value=token, max_age=30*86400, httponly=True, samesite="lax", path="/")
        return resp


@router.post("/auth/register")
def api_register(request: Request, username: str = Form(...), password: str = Form(...),
                 display_name: str = Form(""), email: str = Form(...)):
    from routes.auth import hash_password, create_session
    from crypto_utils import generate_keypair
    import re
    if not username or not password or not email:
        raise HTTPException(status_code=400, detail="Username, password, and email required")
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="Username (3+) and password (6+) required")
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        raise HTTPException(status_code=400, detail="Username can only contain letters, numbers, and underscores")
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    with get_session() as s:
        existing = s.query(User).filter_by(username=username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        existing_email = s.query(User).filter_by(email=email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")
        user_count = s.query(User).count()
        is_first = user_count == 0
        salt, pwd_hash = hash_password(password)
        priv_key, pub_key = generate_keypair()
        user = User(
            username=username,
            display_name=display_name or username,
            password_hash=salt + ":" + pwd_hash,
            private_key=encrypt_key(priv_key, SECRET_KEY), public_key=pub_key,
            is_remote=False,
            role="admin" if is_first else "user",
            is_admin=is_first,
            email=email,
            email_verified=False,
        )
        s.add(user)
        client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0].strip()
        if client_ip:
            user.recent_ips = [client_ip]
        s.commit()
        token = create_session(user.id)
        resp = JSONResponse(_user_json(user))
        resp.set_cookie(key="session", value=token, max_age=30*86400, httponly=True, samesite="lax", path="/")
        return resp


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
        ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).offset(offset).limit(limit + 1).all()
        posts = [p for p in posts if _can_view(p, user, session)]
        posts = [p for p in posts if not (p.visibility == "mention" and p.is_dm)]
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
        posts = [p for p in posts if _can_view(p, user, session)]
        posts = [p for p in posts if not (p.visibility == "mention" and p.is_dm)]
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
    has_more = len(posts) > limit
    return [_post_json(p, session, user) for p in posts[:limit]], has_more


@router.get("/timeline/{tl_type}")
def api_timeline(request: Request, tl_type: str, limit: int = Query(10), offset: int = Query(0)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
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
        result["ancestors"] = ancestors
    return result


@router.post("/posts")
def api_create_post(
    request: Request,
    content: str = Form(...),
    summary: str = Form(""),
    visibility: str = Form("public"),
    parent_id: int = Form(None),
    dm_target_id: int = Form(None),
    share_url: str = Form(""),
):
    user = require_auth(request)
    if share_url:
        content = content + "\n\nseries: " + share_url
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    total_len = len(content) + len(summary)
    if total_len > MAX_POST_LENGTH:
        raise HTTPException(status_code=400, detail=f"Total length exceeds {MAX_POST_LENGTH}")
    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"

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
        )
        s.add(post)
        s.flush()
        post.ap_id = f"{BASE_URL}/@{user.username}/{post.number}"
        if parent_id:
            parent = s.query(Post).filter_by(id=parent_id).first()
            if parent:
                pass
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

        try:
            create_activity = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/activities/create/{post.id}",
                "type": "Create",
                "actor": user.actor_uri(),
                "object": post.to_ap_note(),
            }
            if visibility == "mention":
                if post.mentioned_user_ids:
                    with get_session() as ap_s:
                        mu_users = ap_s.query(User).filter(
                            User.id.in_(post.mentioned_user_ids), User.is_remote == True
                        ).all()
                        for mu in mu_users:
                            _post_to_inbox(mu.inbox_uri(), create_activity, user)
            else:
                broadcast_to_followers(user, create_activity)
        except Exception as e:
            logger.warning("Failed to broadcast federation activity: %s", e)

        try:
            broadcast("new_post", {"post_id": post.id, "author_id": user.id})
        except Exception as e:
            logger.warning("Failed to broadcast new_post: %s", e)
        return _post_json(post, s, user)


@router.post("/posts/{post_id}/edit")
def api_edit_post(request: Request, post_id: int, content: str = Form(...), summary: str = Form("")):
    user = require_auth(request)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, author_id=user.id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.content = content
        post.summary = summary
        s.commit()
        return _post_json(post, s, user)


@router.post("/posts/{post_id}/delete")
def api_delete_post(request: Request, post_id: int):
    user = require_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id and not user.is_admin:
            raise HTTPException(status_code=403, detail="Cannot delete this post")
        post.is_deleted = True
        s.commit()
    return {"ok": True}


@router.post("/posts/{post_id}/like")
def api_like_post(request: Request, post_id: int):
    user = require_auth(request)
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
    return {"ok": True}


@router.post("/posts/{post_id}/unlike")
def api_unlike_post(request: Request, post_id: int):
    user = require_auth(request)
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
    return {"ok": True}


@router.post("/posts/{post_id}/boost")
def api_boost_post(request: Request, post_id: int):
    user = require_auth(request)
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
    return {"ok": True}


@router.post("/posts/{post_id}/bookmark")
def api_bookmark_post(request: Request, post_id: int):
    user = require_auth(request)
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
    user = require_auth(request)
    with get_session() as s:
        existing = s.query(Bookmark).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            s.delete(existing)
            s.commit()
    return {"ok": True}


@router.get("/bookmarks")
def api_bookmarks(request: Request):
    user = require_auth(request)
    with get_session() as s:
        bookmarks = s.query(Bookmark).filter_by(user_id=user.id).order_by(desc(Bookmark.created_at)).limit(50).all()
        return {"posts": [_post_json(b.post, s, user) for b in bookmarks if b.post and not b.post.is_deleted]}


@router.post("/posts/{post_id}/unboost")
def api_unboost_post(request: Request, post_id: int):
    user = require_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            s.delete(existing)
            s.query(Notification).filter_by(
                from_user_id=user.id, notification_type="boost", post_id=post_id
            ).delete()
            remaining = s.query(Boost).filter_by(post_id=post_id).count()
            if remaining == 0:
                post.bumped_at = None
            s.commit()
    return {"ok": True}


# ── User / Profile API ──

@router.get("/users/{username}")
def api_get_profile(request: Request, username: str):
    user = get_current_user(request)
    with get_session() as s:
        profile = s.query(User).filter_by(username=username).first()
        if "@" in username:
            parts = username.split("@")
            if len(parts) == 2:
                remote_user, remote_domain = parts
                actor_url = f"https://{remote_domain}/@{remote_user}"
                from activitypub import _resolve_actor
                _resolve_actor(actor_url)
                profile = s.query(User).filter_by(username=username).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
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
        ).limit(50).all()
        posts = [p for p in posts if _can_view(p, user, s)]
        followers_count = s.query(Follow).filter_by(following_id=profile.id, accepted=True).count()
        following_count = s.query(Follow).filter_by(follower_id=profile.id, accepted=True).count()
        is_following = s.query(Follow).filter_by(
            follower_id=user.id, following_id=profile.id, accepted=True
        ).first() is not None if user else False
        is_follow_pending = s.query(Follow).filter_by(
            follower_id=user.id, following_id=profile.id, accepted=False
        ).first() is not None if user else False
        has_pending_follower = s.query(Follow).filter_by(
            follower_id=profile.id, following_id=user.id, accepted=False
        ).first() is not None if user else False
        is_follower = s.query(Follow).filter_by(
            follower_id=profile.id, following_id=user.id, accepted=True
        ).first() is not None if user else False
        novels_q = s.query(Novel).filter_by(author_id=profile.id)
        if not user or profile.id != user.id:
            novels_q = novels_q.filter(Novel.visibility != "private")
        novels = novels_q.order_by(desc(Novel.updated_at)).all()
        followers = s.query(Follow).filter_by(following_id=profile.id, accepted=True).all()
        following = s.query(Follow).filter_by(follower_id=profile.id, accepted=True).all()
        return {
            "profile": _user_json(profile),
            "posts": [_post_json(p, s, user) for p in posts],
            "novels": [_novel_json(n, s) for n in novels],
            "followers": [{"user": _user_json(f.follower)} for f in followers],
            "following": [{"user": _user_json(f.following)} for f in following],
            "followers_count": followers_count,
            "following_count": following_count,
            "is_following": is_following,
            "is_follow_pending": is_follow_pending,
            "has_pending_follower": has_pending_follower,
            "is_follower": is_follower,
            "is_mine": profile.id == user.id if user else False,
        }


@router.post("/users/{username}/follow")
def api_follow(request: Request, username: str):
    user = require_auth(request)
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
    return {"ok": True}


@router.post("/users/{username}/approve-follow")
def api_approve_follow(request: Request, username: str):
    user = require_auth(request)
    with get_session() as s:
        target = s.query(Follow).filter_by(
            following_id=user.id
        ).join(User, Follow.follower_id == User.id).filter(User.username == username).first()
        if not target:
            raise HTTPException(status_code=404, detail="Follow request not found")
        target.accepted = True
        s.query(Notification).filter_by(
            from_user_id=target.follower_id, user_id=user.id, notification_type="follow_request"
        ).update({"notification_type": "follow"})
        s.commit()
    return {"ok": True}

@router.post("/users/{username}/remove-follower")
def api_remove_follower(request: Request, username: str):
    user = require_auth(request)
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

@router.post("/users/{username}/reject-follow")
def api_reject_follow(request: Request, username: str):
    user = require_auth(request)
    with get_session() as s:
        target = s.query(Follow).filter_by(
            following_id=user.id
        ).join(User, Follow.follower_id == User.id).filter(User.username == username).first()
        if not target:
            raise HTTPException(status_code=404, detail="Follow request not found")
        s.query(Notification).filter_by(
            from_user_id=target.follower_id, user_id=user.id, notification_type="follow_request"
        ).delete()
        s.delete(target)
        s.commit()
    return {"ok": True}

@router.post("/users/{username}/unfollow")
def api_unfollow(request: Request, username: str):
    user = require_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=username, is_remote=False).first()
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
    return {"ok": True}


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
    if other_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot chat with yourself")
    with get_session() as s:
        other = s.query(User).get(other_id)
        if not other:
            raise HTTPException(status_code=404, detail="User not found")
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
        posts = s.query(Post).filter(
            Post.visibility == "mention",
            Post.is_deleted == False,
            Post.created_at >= three_months_ago,
        ).order_by(desc(Post.created_at)).limit(200).all()
        uid_str = str(user.id)
        author_map = {}
        oid_str = str(user.id)
        for p in posts:
            mu = str(p.mentioned_user_ids or [])
            other_id = None
            if p.author_id == user.id:
                for tid in [int(x) for x in re.findall(r'\d+', mu) if x]:
                    if tid != user.id:
                        other_id = tid
                        break
            elif oid_str in mu:
                other_id = p.author_id
            if other_id and other_id not in author_map:
                author = s.query(User).get(other_id)
                author_map[other_id] = {"user": author, "all_msgs": []}
            if other_id:
                author_map[other_id]["all_msgs"].append(p)
        result = []
        import re as _re
        for aid, data in author_map.items():
            u = data["user"]
            if u and u.id != user.id:
                sorted_msgs = sorted(data["all_msgs"], key=lambda x: x.created_at or datetime.datetime.min, reverse=True)
                previews = []
                for msg in sorted_msgs[:3]:
                    text = _re.sub(r'<[^>]*>', '', msg.content or "")
                    text = _re.sub(r'@\w+', '', text).strip()
                    is_me = msg.author_id == user.id
                    previews.append({"text": text[:60], "is_me": is_me})
                entry = _user_json(u)
                entry["latest_previews"] = previews
                entry["latest_time"] = _fmt_dt(sorted_msgs[0].created_at)
                result.append(entry)
    return {"users": result}


@router.get("/notifications")
def api_notifications(request: Request, filter_type: str = Query("")):
    user = require_auth(request)
    with get_session() as s:
        q = s.query(Notification).filter_by(user_id=user.id)
        if filter_type == "follow":
            q = q.filter(Notification.notification_type.in_(["follow", "follow_request"]))
        elif filter_type:
            q = q.filter_by(notification_type=filter_type)
        notifs = q.order_by(desc(Notification.created_at)).limit(50).all()

        result = []
        for n in notifs:
            from_user = s.query(User).get(n.from_user_id) if n.from_user_id else None
            post = s.query(Post).get(n.post_id) if n.post_id else None
            item = {
                "id": n.id,
                "type": n.notification_type,
                "created_at": _fmt_dt(n.created_at),
                "is_read": n.is_read,
                "from_user": _user_json(from_user) if from_user else None,
                "post": _post_json(post, s, user) if post and not post.is_deleted and _can_view(post, user, s) else None,
            }
            result.append(item)

        # mark as read
        s.query(Notification).filter_by(user_id=user.id, is_read=False).update({"is_read": True})
        s.commit()

    return {"notifications": result}


# ── Novels / Episodes API ──

@router.get("/novels")
def api_novels(request: Request):
    with get_session() as s:
        novels = s.query(Novel).filter_by(is_published=True, visibility="public").order_by(desc(Novel.updated_at)).all()
        result = {"novels": [_novel_json(n, s) for n in novels]}
    return result


@router.get("/novels/my")
def api_my_novels(request: Request):
    user = require_auth(request)
    with get_session() as s:
        novels = s.query(Novel).filter_by(author_id=user.id).order_by(desc(Novel.updated_at)).all()
        result = {"novels": [_novel_json(n, s) for n in novels]}
    return result


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
    tag_names = " ".join(t.name for t in (n.tag_list or [])) if n.tag_list else (n.tags or "")
    return {
        "id": n.id,
        "number": n.number or "",
        "title": n.title,
        "description": n.description or "",
        "cover_image": n.cover_image or "",
        "tags": tag_names,
        "is_completed": n.is_completed,
        "is_published": n.is_published,
        "episode_count": n.episode_count or 0,
        "total_views": n.total_views or 0,
        "visibility": n.visibility or "public",
        "created_at": _fmt_dt(n.created_at),
        "updated_at": _fmt_dt(n.updated_at),
        "author": author,
        "author_id": n.author_id,
    }


@router.post("/novels/new")
def api_create_novel(request: Request, title: str = Form(...), description: str = Form(""),
                     tags: str = Form(""), visibility: str = Form("public"),
                     cover_image: str = Form("")):
    user = require_auth(request)
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    with get_session() as s:
        import secrets
        novel_number = secrets.token_hex(4)
        novel = Novel(author_id=user.id, title=title, description=description, tags=tags,
                      visibility=visibility, is_published=visibility != "private",
                      cover_image=cover_image, number=novel_number)
        s.add(novel)
        s.flush()
        _sync_tags(novel, s)
        nid = novel.id
        s.commit()
    return {"ok": True, "novel_id": nid}


@router.get("/novels/{novel_id}")
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
        result = {
            "novel": _novel_json(novel, s),
            "episodes": [_episode_json(e) for e in episodes],
            "author": _user_json(author) if author else None,
            "is_mine": user.id == novel.author_id if user else False,
        }
    return result


@router.post("/novels/{novel_id}/edit")
def api_edit_novel(request: Request, novel_id: int, title: str = Form(...), description: str = Form(""),
                   tags: str = Form(""), visibility: str = Form("public"), is_completed: bool = Form(False),
                   cover_image: str = Form("")):
    user = require_auth(request)
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        novel.title = title
        novel.description = description
        novel.tags = tags
        novel.visibility = visibility
        novel.is_completed = is_completed
        novel.is_published = visibility != "private"
        if cover_image:
            novel.cover_image = cover_image
        s.flush()
        _sync_tags(novel, s)
        s.commit()
    return {"ok": True}


@router.post("/novels/{novel_id}/episodes/new")
def api_create_episode(request: Request, novel_id: int, title: str = Form(...), content: str = Form(...),
                       summary: str = Form(""), comment: str = Form(""),
                       announce: bool = Form(False), visibility: str = Form("public"),
                       announce_comment: str = Form("")):
    user = require_auth(request)
    if not title.strip() or not content.strip():
        raise HTTPException(status_code=400, detail="Title and content are required")
    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        max_ep = s.query(Episode).filter_by(novel_id=novel.id).order_by(desc(Episode.episode_number)).first()
        next_num = (max_ep.episode_number + 1) if max_ep else 1
        episode = Episode(novel_id=novel.id, episode_number=next_num, title=title, content=content, summary=summary, comment=comment)
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
                visibility=visibility,
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
        eid = episode.id
    return {"ok": True, "episode_id": eid}


@router.get("/novels/{novel_id}/episodes/{episode_id}")
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
        result = {
            "episode": _episode_json(episode),
            "novel": _novel_json(novel, s),
            "is_mine": is_mine,
            "prev_episode": _episode_json(prev_ep) if prev_ep else None,
            "next_episode": _episode_json(next_ep) if next_ep else None,
        }
    return result


@router.post("/novels/{novel_id}/episodes/{episode_id}/edit")
def api_edit_episode(request: Request, novel_id: int, episode_id: int,
                     title: str = Form(...), content: str = Form(...),
                     summary: str = Form(""), comment: str = Form(""),
                     is_published: bool = Form(True), announce: bool = Form(False),
                     visibility: str = Form("public"), announce_comment: str = Form("")):
    user = require_auth(request)
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


@router.post("/novels/{novel_id}/episodes/{episode_id}/delete")
def api_delete_episode(request: Request, novel_id: int, episode_id: int):
    user = require_auth(request)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode or episode.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Episode not found")
        s.delete(episode)
        s.commit()
    return {"ok": True}


@router.post("/novels/{novel_id}/delete")
def api_delete_novel(request: Request, novel_id: int):
    user = require_auth(request)
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


def _cleanup_avatars():
    import time
    from utils.storage import get_storage
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        return
    with get_session() as s:
        used_urls = {u.profile_image for u in s.query(User).filter(User.profile_image != "").all()}
    now = time.time()
    for key in storage.list_keys("avatars"):
        url = storage.url(key)
        if url in used_urls:
            continue
        mtime = storage.mtime(key)
        if mtime is not None and now - mtime > 86400:
            storage.delete(key)


@router.post("/settings/update")
def api_update_settings(request: Request, default_visibility: str = Form("public"),
                        series_default_visibility: str = Form("public"),
                        episode_default_visibility: str = Form("public"),
                        is_locked: bool = Form(False),
                        show_badge: bool = Form(False)):
    user = require_auth(request)
    valid_post = ("public", "home", "followers", "mention")
    valid_series = ("public", "unlisted", "private")
    if default_visibility not in valid_post:
        default_visibility = "public"
    if series_default_visibility not in valid_series:
        series_default_visibility = "public"
    if episode_default_visibility not in valid_post:
        episode_default_visibility = "public"
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        db.default_visibility = default_visibility
        db.series_default_visibility = series_default_visibility
        db.episode_default_visibility = episode_default_visibility
        db.is_locked = is_locked
        if user.role in ("admin", "moderator"):
            db.show_badge = show_badge
        s.commit()
    return {"ok": True}


@router.post("/profile/update")
def api_update_profile(request: Request, display_name: str = Form(""), summary: str = Form(""),
                       image: UploadFile = File(None)):
    from utils.storage import get_storage
    user = require_auth(request)
    storage = get_storage()
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        db.display_name = display_name
        db.summary = summary
        if image and image.filename:
            from PIL import Image as PILImage
            import io
            from uuid import uuid4
            key = f"avatars/local/u{user.id}_{uuid4().hex[:8]}.webp"
            img = PILImage.open(image.file)
            img.thumbnail((400, 400), PILImage.Resampling.LANCZOS)
            if img.mode in ("RGBA", "P"):
                bg = PILImage.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = bg
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=100)
            new_url = storage.save(key, out.getvalue(), "image/webp")
            old = db.profile_image
            db.profile_image = new_url
            s.flush()
            if old:
                storage.delete(old)
        s.commit()
    _cleanup_avatars()
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

@router.get("/by-number/{username}/{number}")
def api_by_number(request: Request, username: str, number: str):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        author = s.query(User).filter_by(username=username).first()
        if not author:
            raise HTTPException(status_code=404, detail="User not found")
        post = s.query(Post).filter_by(author_id=author.id, number=number).first()
        if not post or not _can_view(post, user, s):
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

        latest_ep = s.query(
            Episode.novel_id,
            func.max(Episode.created_at).label("max_created")
        ).group_by(Episode.novel_id).subquery()

        novels = s.query(Novel).options(
            selectinload(Novel.author),
            selectinload(Novel.tag_list),
        ).outerjoin(
            latest_ep, Novel.id == latest_ep.c.novel_id
        ).filter(
            Novel.visibility == "public",
            Novel.is_published == True,
        ).order_by(
            desc(func.coalesce(latest_ep.c.max_created, Novel.created_at))
        ).limit(20).all()

        return {
            "posts": [_post_json(p, s, user) for p in posts],
            "novels": [_novel_json(n, s) for n in novels],
        }


@router.get("/search")
def api_search(request: Request, q: str = Query("")):
    user = get_current_user(request)
    query = q.strip()
    if not query:
        return {"posts": [], "novels": [], "users": []}
    with get_session() as s:
        pattern = f"%{query}%"
        posts = s.query(Post).options(selectinload(Post.author)).filter(
            Post.content.ilike(pattern),
            Post.visibility == "public",
            Post.is_deleted == False,
            Post.in_reply_to_id == None,
        ).order_by(desc(Post.created_at)).limit(20).all()
        novels = s.query(Novel).options(selectinload(Novel.author)).filter(
            or_(Novel.title.ilike(pattern), Novel.description.ilike(pattern)),
            Novel.is_published == True,
            Novel.visibility == "public",
        ).order_by(desc(Novel.updated_at)).limit(20).all()
        users = s.query(User).filter(
            User.is_remote == False,
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern)),
        ).limit(20).all()
        return {
            "posts": [_post_json(p, s, user) for p in posts],
            "novels": [_novel_json(n, s) for n in novels],
            "users": [_user_json(u) for u in users],
        }


@router.get("/users/autocomplete")
def api_users_autocomplete(request: Request, q: str = Query("")):
    user = get_current_user(request)
    query = q.strip().lstrip("@")
    if not query:
        return {"users": []}
    with get_session() as s:
        pattern = f"{query}%"
        matches = s.query(User).filter(
            User.is_remote == False,
            User.username.ilike(pattern),
        ).limit(20).all()
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


def _fetch_and_save_ap_object(obj, user):
    """Fetch a remote AP object, resolve its author, save to DB, return post."""
    from activitypub import _sanitize_html
    content = _sanitize_html(obj.get("content", ""))
    if not content:
        return None

    attributed_to = obj.get("attributedTo", "")
    if isinstance(attributed_to, list):
        attributed_to = attributed_to[0] if attributed_to else ""
    if not attributed_to:
        return None

    from activitypub import _resolve_actor
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
        mentioned_names = set(re.findall(r'@(\w+)', content or ""))
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

        post = Post(
            author_id=author_id,
            content=content,
            summary=summary,
            visibility="public",
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
    from activitypub import _validate_url
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
    from activitypub import _validate_url
    if not _validate_url(url):
        return None
    from urllib.parse import urlparse

    # Try unsigned first (many servers serve public posts without auth)
    headers = {"Accept": "application/activity+json"}
    resp = _safe_httpx_get(url, headers=headers)
    if resp:
        try:
            return resp.json()
        except Exception:
            return None

    # Fall back to signed request
    import hashlib, time
    from crypto_utils import sign_string
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    parsed = urlparse(url)
    path = parsed.path or "/"
    signed_string = f"(request-target): get {path}\nhost: {parsed.netloc}\ndate: {date}"
    signature = sign_string(signed_string, get_private_key(user, SECRET_KEY))
    signature_header = (
        f'keyId="{user.actor_uri()}#main-key",'
        f'algorithm="hs2019",'
        f'created="{int(time.time())}",'
        f'headers="(request-target) host date",'
        f'signature="{signature}"'
    )
    headers = {"Accept": "application/activity+json", "Signature": signature_header,
               "Date": date, "Host": parsed.netloc}
    resp = _safe_httpx_get(url, headers=headers)
    if not resp:
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


@router.post("/fetch-actor")
def api_fetch_actor(request: Request, url: str = Form(...)):
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    from activitypub import _resolve_actor
    _resolve_actor(url)
    actor_id = None
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    username_from_url = path.split("/@")[-1] if "/@" in path else path.split("/")[-1]
    if username_from_url:
        remote_username = f"{username_from_url}@{parsed.netloc}"
        with get_session() as s:
            u = s.query(User).filter_by(username=remote_username).first()
            if u:
                actor_id = u.id
    if not actor_id:
        raise HTTPException(status_code=400, detail="Cannot resolve actor")
    with get_session() as s:
        u = s.query(User).get(actor_id)
        if u:
            return _user_json(u)
    raise HTTPException(status_code=400, detail="Cannot resolve actor")


@router.post("/fetch-post")
def api_fetch_post(request: Request, url: str = Form(...)):
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")

    data = _ap_fetch(url, user)
    if not data:
        raise HTTPException(status_code=400, detail="Cannot fetch post")

    obj = data.get("object", data)
    obj_type = data.get("type", obj.get("type", ""))
    if obj_type not in ("Note", "Article"):
        raise HTTPException(status_code=400, detail=f"Not a Note/Article (type={obj_type})")

    # Recursively fetch ancestors
    visited = set()
    def fetch_thread(current_obj, depth=0):
        if depth > 5:
            return
        in_reply_to = current_obj.get("inReplyTo", "")
        if isinstance(in_reply_to, dict):
            in_reply_to = in_reply_to.get("id", "")
        if in_reply_to and in_reply_to not in visited:
            visited.add(in_reply_to)
            parent_data = _ap_fetch(in_reply_to, user)
            if parent_data:
                parent_obj = parent_data.get("object", parent_data)
                fetch_thread(parent_obj, depth + 1)
                try:
                    _fetch_and_save_ap_object(parent_obj, user)
                except Exception as e:
                    logger.warning("Failed to save parent post: %s", e)

    fetch_thread(obj)

    result = _fetch_and_save_ap_object(obj, user)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to save post")
    # Include emoji data so frontend can render immediately
    emojis = []
    with get_session() as es:
        for e in es.query(CustomEmoji).order_by(CustomEmoji.keyword).all():
            emojis.append({"keyword": e.keyword, "file_name": e.file_name, "url": f"/emojis/{e.file_name}", "aliases": e.aliases or []})
    result["_emojis"] = emojis
    return result


EMOJI_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "public", "emojis")


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
                "url": f"/emojis/{e.file_name}",
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
            "url": f"/emojis/{emoji.file_name}",
            "source_url": "",
            "domain": "",
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
        return {"ok": True, "emoji": {"id": emoji.id, "keyword": emoji.keyword, "file_name": emoji.file_name, "category": emoji.category, "aliases": emoji.aliases or [], "url": f"/emojis/{emoji.file_name}", "source_url": emoji.source_url or "", "domain": emoji.domain or ""}}

@router.delete("/emojis/{emoji_id}")
def api_delete_emoji(request: Request, emoji_id: int):
    user = require_auth(request)
    with get_session() as s:
        emoji = s.query(CustomEmoji).get(emoji_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        file_path = os.path.join(EMOJI_DIR, emoji.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
        s.delete(emoji)
        s.commit()
        return {"ok": True}


@router.get("/admin/stats")
def api_admin_stats(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
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
    if user.role not in ("admin", "moderator"):
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
            qb = qb.filter(User.role == "admin")
        elif role == "moderator":
            qb = qb.filter(User.role == "moderator")
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
            })
        return {"users": result}


@router.get("/admin/users/{user_id}")
def api_admin_user_detail(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
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
            "is_suspended": getattr(u, 'is_suspended', False),
            "is_sensitive": getattr(u, 'is_sensitive', False),
            "moderation_note": getattr(u, 'moderation_note', '') or '',
            "email_verified": getattr(u, 'email_verified', False),
            "summary": u.summary or "",
        }


@router.post("/admin/users/{user_id}/reset-password")
def api_admin_reset_password(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    from routes.auth import hash_password
    import secrets
    new_pass = secrets.token_hex(8)
    salt, hsh = hash_password(new_pass)
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        u.password_hash = salt + ":" + hsh
        u.session_token = ""
        s.commit()
    return {"ok": True, "new_password": new_pass}


@router.post("/admin/users/{user_id}/change-email")
def api_admin_change_email(request: Request, user_id: int, email: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        u.email = email
        u.email_verified = False
        s.commit()
    return {"ok": True}


@router.post("/admin/users/{user_id}/change-role")
def api_admin_change_role(request: Request, user_id: int, role: str = Form("user")):
    user = require_auth(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can change roles")
    if role not in ("user", "moderator", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        u.role = role
        u.is_admin = role == "admin"
        s.commit()
    return {"ok": True}


@router.post("/admin/users/{user_id}/verify-email")
def api_admin_verify_email(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        u.email_verified = True
        s.commit()
    return {"ok": True}


@router.post("/admin/users/{user_id}/remove-avatar")
def api_admin_remove_avatar(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
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
    return {"ok": True}


@router.post("/admin/users/suspend")
def api_admin_suspend_users(request: Request, user_ids: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    ids = [int(i) for i in user_ids.split(",") if i.strip()]
    with get_session() as s:
        s.query(User).filter(User.id.in_(ids)).update({"is_suspended": True}, synchronize_session=False)
        s.commit()
    return {"ok": True}


@router.post("/admin/users/unsuspend")
def api_admin_unsuspend_users(request: Request, user_ids: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    ids = [int(i) for i in user_ids.split(",") if i.strip()]
    with get_session() as s:
        s.query(User).filter(User.id.in_(ids)).update({"is_suspended": False}, synchronize_session=False)
        s.commit()
    return {"ok": True}


@router.post("/admin/users/{user_id}/note")
def api_admin_user_note(request: Request, user_id: int, note: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u: raise HTTPException(status_code=404, detail="User not found")
        u.moderation_note = note
        s.commit()
    return {"ok": True}


@router.post("/admin/users/{user_id}/moderate")
def api_admin_moderate(request: Request, user_id: int, action: str = Form(...), send_email: bool = Form(False), message: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    valid_actions = ("warning", "freeze", "sensitive", "limit", "suspend", "unsuspend")
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u: raise HTTPException(status_code=404, detail="User not found")

        if action == "warning":
            pass  # Just a warning, no automatic action
        elif action == "freeze":
            u.is_suspended = True
        elif action == "sensitive":
            u.is_sensitive = True
        elif action == "limit":
            u.is_sensitive = True
            u.is_suspended = False
        elif action == "suspend":
            u.is_suspended = True
        elif action == "unsuspend":
            u.is_suspended = False

        s.commit()

        if send_email and u.email:
            try:
                from email.mime.text import MIMEText
                import smtplib
                from config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
                action_names = {"warning": "경고", "freeze": "동결", "sensitive": "민감 처리", "limit": "제한", "suspend": "정지", "unsuspend": "정지 해제"}
                msg = MIMEText(f"계정에 {action_names.get(action, action)} 조치가 적용되었습니다.\n서버 관리팀")
                msg["Subject"] = f"[WRIT] 계정 {action_names.get(action, action)} 안내"
                msg["From"] = SMTP_FROM or "noreply@writ.local"
                msg["To"] = u.email
                with smtplib.SMTP(SMTP_SERVER or "localhost", SMTP_PORT or 25, timeout=10) as smtp:
                    if SMTP_USER:
                        smtp.login(SMTP_USER, SMTP_PASSWORD or "")
                    smtp.send_message(msg)
            except Exception as e:
                logger.warning("Failed to send moderation email to %s: %s", u.email, e)
    return {"ok": True, "action": action}


@router.post("/admin/users/{user_id}/toggle-sensitive")
def api_admin_toggle_sensitive(request: Request, user_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u: raise HTTPException(status_code=404, detail="User not found")
        u.is_sensitive = not u.is_sensitive
        s.commit()
        return {"ok": True, "is_sensitive": u.is_sensitive}
