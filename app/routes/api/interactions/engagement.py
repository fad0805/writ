"""Interaction endpoints — follow, DM, notification, mute/block, like, boost, bookmark, vote, react, pin."""
import logging
import threading

from fastapi import APIRouter, Request, HTTPException, Query
from sqlalchemy import desc

from app.models import Post, Like, Bookmark, CustomEmoji
from app.serializers import _post_json
from app.core.interactions import like_post, unlike_post, boost_post, unboost_post
from app.db.database import get_session
from app.core.auth import require_active_auth

from app.core.visibility import _can_view

logger = logging.getLogger("writ.api.engagement")

engagement_router = APIRouter()


# ── Post interactions (likes/boosts/bookmarks/polls/reactions/pins) —————————————————

@engagement_router.post("/posts/{post_id}/like")
def api_like_post(request: Request, post_id: int, reaction: str = "★"):
    user = require_active_auth(request)
    if reaction.startswith(":") and reaction.endswith(":"):
        keyword = reaction[1:-1].strip().lower().replace(" ", "_")
        with get_session() as s:
            is_local_defined = s.query(CustomEmoji).filter_by(keyword=keyword, domain="").first()
            if not is_local_defined:
                raise HTTPException(status_code=400, detail=f"The emoji '{reaction}' is not registered on this server.")

    def _do_like():
        try:
            with get_session() as s:
                like_post(s, user, post_id, reaction)
        except Exception:
            pass

    threading.Thread(target=_do_like, daemon=True).start()
    return {"ok": True}


@engagement_router.post("/posts/{post_id}/unlike")
def api_unlike_post(request: Request, post_id: int):
    user = require_active_auth(request)

    def _do_unlike():
        try:
            with get_session() as s:
                unlike_post(s, user, post_id)
        except Exception:
            pass

    threading.Thread(target=_do_unlike, daemon=True).start()
    return {"ok": True}


@engagement_router.post("/posts/{post_id}/boost")
def api_boost_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id and post.visibility in ("followers", "mention"):
            raise HTTPException(status_code=403, detail="Cannot boost followers-only or mention-only posts from other users")
        boost_post(s, user, post_id)
        return {"ok": True}


@engagement_router.post("/posts/{post_id}/bookmark")
def api_bookmark_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Bookmark).filter_by(user_id=user.id, post_id=post_id).first()
        if not existing:
            s.add(Bookmark(user_id=user.id, post_id=post_id))
            s.commit()
    return {"ok": True}


@engagement_router.post("/posts/{post_id}/unbookmark")
def api_unbookmark_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(Bookmark).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            s.delete(existing)
            s.commit()
    return {"ok": True}


@engagement_router.get("/bookmarks")
def api_bookmarks(request: Request, limit: int = Query(20), offset: int = Query(0)):
    user = require_active_auth(request)
    with get_session() as s:
        raw = s.query(Bookmark).filter_by(user_id=user.id).order_by(desc(Bookmark.created_at)).offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        posts = [_post_json(b.post, s, user) for b in raw[:limit] if b.post and not b.post.is_deleted and _can_view(b.post, user, s)]
        return {"posts": posts, "has_more": has_more}


@engagement_router.get("/favorites")
def api_favorites(request: Request, limit: int = Query(10), offset: int = Query(0)):
    limit = min(limit, 20)
    user = require_active_auth(request)
    with get_session() as s:
        raw = s.query(Like).filter_by(user_id=user.id).order_by(desc(Like.created_at)).offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        posts = [_post_json(l.post, s, user) for l in raw[:limit] if l.post and not l.post.is_deleted and _can_view(l.post, user, s)]
        return {"posts": posts, "has_more": has_more}


@engagement_router.post("/posts/{post_id}/unboost")
def api_unboost_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        unboost_post(s, user, post_id)
    return {"ok": True}

