import re
import datetime
from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy import desc, or_, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from models import User, Post, Follow, Like, Boost, Notification, Novel, Episode, Tag, get_session
from routes.auth import require_auth, get_current_user
from activitypub import broadcast_to_followers, _post_to_inbox
from config import BASE_URL, MAX_POST_LENGTH

router = APIRouter(prefix="/api")


# ── helpers ──

def _post_json(p, session, user):
    liked = session.query(Like).filter_by(user_id=user.id, post_id=p.id).first() is not None if user else False
    boosted = session.query(Boost).filter_by(user_id=user.id, post_id=p.id).first() is not None if user else False
    latest_boost = session.query(Boost).filter_by(post_id=p.id).order_by(desc(Boost.created_at)).first()
    booster = session.query(User).get(latest_boost.user_id) if latest_boost else None
    return {
        "id": p.id,
        "number": p.number or "",
        "content": p.content,
        "summary": p.summary or "",
        "visibility": p.visibility or "public",
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "author": _user_json(p.author),
        "likes_count": p.likes_count,
        "boosts_count": p.boosts_count,
        "replies_count": p.replies_count,
        "liked": liked,
        "boosted": boosted,
        "is_mine": p.author_id == user.id if user else False,
        "reply_context": _reply_context(p),
        "boosted_by": _user_json(booster) if booster and booster.id != p.author_id else None,
    }


def _user_json(u):
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "avatar": u.profile_image or "",
        "summary": u.summary or "",
        "is_admin": u.is_admin,
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
        token = create_session(db_user.id)
        resp = JSONResponse(_user_json(db_user))
        resp.set_cookie(key="session", value=token, max_age=30*86400, httponly=True, samesite="lax", path="/")
        return resp


@router.post("/auth/register")
def api_register(request: Request, username: str = Form(...), password: str = Form(...),
                 display_name: str = Form("")):
    from routes.auth import hash_password, create_session
    from crypto_utils import generate_keypair
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="Username (3+) and password (6+) required")
    with get_session() as s:
        existing = s.query(User).filter_by(username=username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        salt, pwd_hash = hash_password(password)
        priv_key, pub_key = generate_keypair()
        user = User(
            username=username,
            display_name=display_name or username,
            password_hash=salt + ":" + pwd_hash,
            private_key=priv_key, public_key=pub_key,
            is_remote=False,
        )
        s.add(user)
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
):
    user = require_auth(request)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    total_len = len(content) + len(summary)
    if total_len > MAX_POST_LENGTH:
        raise HTTPException(status_code=400, detail=f"Total length exceeds {MAX_POST_LENGTH}")
    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"

    mentioned_ids = _parse_mentions(content)
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
        except Exception:
            pass

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
        post = s.query(Post).filter_by(id=post_id, author_id=user.id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
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
            twentieth = s.query(Post.created_at).filter(
                Post.is_deleted == False,
            ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).offset(19).limit(1).scalar()
            if twentieth and post.created_at and post.created_at < twentieth:
                post.bumped_at = datetime.datetime.now(datetime.timezone.utc)
            if post.author_id != user.id:
                s.add(Notification(user_id=post.author_id, from_user_id=user.id, notification_type="boost", post_id=post_id))
            s.commit()
    return {"ok": True}


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
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        boosted_ids = [b.post_id for b in s.query(Boost).filter_by(user_id=profile.id).all()]
        posts = s.query(Post).options(
            selectinload(Post.author)
        ).filter(
            or_(
                Post.author_id == profile.id,
                Post.id.in_(boosted_ids),
            ),
            Post.is_deleted == False,
        ).order_by(desc(func.coalesce(Post.bumped_at, Post.created_at))).limit(50).all()
        posts = [p for p in posts if _can_view(p, user, s)]
        followers_count = s.query(Follow).filter_by(following_id=profile.id, accepted=True).count()
        following_count = s.query(Follow).filter_by(follower_id=profile.id, accepted=True).count()
        is_following = s.query(Follow).filter_by(
            follower_id=user.id, following_id=profile.id, accepted=True
        ).first() is not None if user else False
        novels = s.query(Novel).filter_by(author_id=profile.id).order_by(desc(Novel.updated_at)).all()
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
            s.add(Follow(follower_id=user.id, following_id=target.id, accepted=True))
            s.add(Notification(user_id=target.id, from_user_id=user.id, notification_type="follow"))
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
            s.query(Notification).filter_by(
                from_user_id=user.id, user_id=target.id, notification_type="follow"
            ).delete()
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

@router.get("/notifications")
def api_notifications(request: Request, filter_type: str = Query("")):
    user = require_auth(request)
    with get_session() as s:
        q = s.query(Notification).filter_by(user_id=user.id)
        if filter_type:
            q = q.filter_by(notification_type=filter_type)
        notifs = q.order_by(desc(Notification.created_at)).limit(50).all()

        result = []
        for n in notifs:
            from_user = s.query(User).get(n.from_user_id) if n.from_user_id else None
            post = s.query(Post).get(n.post_id) if n.post_id else None
            item = {
                "id": n.id,
                "type": n.notification_type,
                "created_at": n.created_at.isoformat() if n.created_at else None,
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
        novels = s.query(Novel).filter_by(is_published=True).order_by(desc(Novel.updated_at)).all()
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
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
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
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        episodes = s.query(Episode).filter_by(novel_id=novel_id).order_by(Episode.episode_number).all()
        author = s.query(User).get(novel.author_id)
        result = {
            "novel": _novel_json(novel, s),
            "episodes": [_episode_json(e) for e in episodes],
            "author": _user_json(author) if author else None,
            "is_mine": user.id == novel.author_id,
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
                       summary: str = Form(""), announce: bool = Form(False), visibility: str = Form("public")):
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
        episode = Episode(novel_id=novel.id, episode_number=next_num, title=title, content=content, summary=summary)
        s.add(episode)
        s.flush()
        if announce:
            import secrets
            import secrets
            ep_post_number = secrets.token_hex(4)
            post = Post(
                author_id=user.id,
                content=f'📖 <a href="{BASE_URL}/novels/{novel.id}/episodes/{episode.id}">[{novel.title}] {next_num}화: {title}</a>\n\n{summary or ""}',
                summary=f"[소설] {novel.title} - {next_num}화",
                visibility=visibility,
                number=ep_post_number,
                novel_id=novel.id,
                episode_id=episode.id,
                ap_id="",
            )
            s.add(post)
            s.flush()
            post.ap_id = f"{BASE_URL}/@{user.username}/{ep_post_number}"
            episode.announcement_post_id = post.id
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
            except Exception:
                s.commit()
        else:
            s.commit()
        eid = episode.id
    return {"ok": True, "episode_id": eid}


@router.get("/novels/{novel_id}/episodes/{episode_id}")
def api_get_episode(request: Request, novel_id: int, episode_id: int):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        novel = episode.novel
        is_mine = novel.author_id == user.id
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
                     summary: str = Form(""), is_published: bool = Form(True)):
    user = require_auth(request)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode or episode.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Episode not found")
        episode.title = title
        episode.content = content
        episode.summary = summary
        episode.is_published = is_published
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
        "views": e.views or 0,
        "is_published": e.is_published,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _cleanup_avatars():
    import os, time
    from config import AVATAR_STORAGE_PATH
    if not os.path.isdir(AVATAR_STORAGE_PATH):
        return
    with get_session() as s:
        used = set()
        for u in s.query(User).filter(User.profile_image != "").all():
            path = u.profile_image.lstrip("/")
            abspath = os.path.abspath(path) if os.path.isfile(path) else None
            if abspath:
                used.add(abspath)
    now = time.time()
    for fname in os.listdir(AVATAR_STORAGE_PATH):
        fpath = os.path.join(AVATAR_STORAGE_PATH, fname)
        if not os.path.isfile(fpath):
            continue
        if os.path.abspath(fpath) in used:
            continue
        if now - os.path.getmtime(fpath) > 86400:
            os.remove(fpath)


@router.post("/profile/update")
def api_update_profile(request: Request, display_name: str = Form(""), summary: str = Form(""),
                       image: UploadFile = File(None)):
    from config import AVATAR_STORAGE_PATH, AVATAR_URL_PREFIX
    user = require_auth(request)
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        db.display_name = display_name
        db.summary = summary
        if image and image.filename:
            import os
            os.makedirs(AVATAR_STORAGE_PATH, exist_ok=True)
            ext = (image.filename.rsplit(".", 1)[-1] if "." in image.filename else "jpg").lower()
            if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                ext = "jpg"
            from uuid import uuid4
            filename = f"u{user.id}_{uuid4().hex[:8]}.{ext}"
            filepath = os.path.join(AVATAR_STORAGE_PATH, filename)
            with open(filepath, "wb") as f:
                f.write(image.file.read())
            new_path = f"{AVATAR_URL_PREFIX}/{filename}"
            old = db.profile_image
            db.profile_image = new_path
            s.flush()
            if old:
                old_path = old.lstrip("/")
                if os.path.isfile(old_path) and os.path.abspath(old_path) != os.path.abspath(filepath):
                    os.remove(old_path)
        s.commit()
    _cleanup_avatars()
    return {"ok": True}


@router.get("/by-series-number/{username}/{number}")
def api_by_series_number(request: Request, username: str, number: str):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        author = s.query(User).filter_by(username=username).first()
        if not author:
            raise HTTPException(status_code=404, detail="User not found")
        novel = s.query(Novel).filter_by(author_id=author.id, number=number).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        return {"id": novel.id}


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
        return {"posts": [_post_json(p, s, user) for p in posts]}


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
    content = obj.get("content", "")
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

    with get_session() as s:
        existing = s.query(Post).filter_by(ap_id=ap_id).first()
        if existing:
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
            except Exception:
                pass
        s.add(post)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            existing = s.query(Post).filter_by(ap_id=ap_id).first()
            if existing:
                return _post_json(existing, s, user)
            return None
        return _post_json(post, s, user)


def _ap_fetch(url, user):
    """Fetch a remote URL with HTTP Signature, return parsed JSON."""
    import httpx, hashlib
    from urllib.parse import urlparse
    from crypto_utils import sign_string
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    parsed = urlparse(url)
    path = parsed.path or "/"
    signed_string = f"(request-target): get {path}\nhost: {parsed.netloc}\ndate: {date}"
    signature = sign_string(signed_string, user.private_key)
    signature_header = (
        f'keyId="{user.actor_uri()}#main-key",'
        f'algorithm="rsa-sha256",'
        f'headers="(request-target) host date",'
        f'signature="{signature}"'
    )
    headers = {"Accept": "application/activity+json", "Signature": signature_header,
               "Date": date, "Host": parsed.netloc}
    resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
    if resp.status_code != 200:
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
                except Exception:
                    pass

    fetch_thread(obj)

    result = _fetch_and_save_ap_object(obj, user)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to save post")
    return result
