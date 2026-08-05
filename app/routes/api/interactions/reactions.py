"""Interaction endpoints — react/unreact for posts."""
import logging
import threading

from fastapi import APIRouter, Request, Form, HTTPException
from sqlalchemy import func

from app.models import Post, Like, CustomEmoji
from app.core.interactions import react_post, unreact_post
from app.db.database import get_session
from app.routes.auth import require_active_auth

from app.core.visibility import _can_view

logger = logging.getLogger("writ.api.reactions")

reactions_router = APIRouter()


@reactions_router.post("/posts/{post_id}/react")
def api_react_post(request: Request, post_id: int, emoji: str = Form(...)):
    user = require_active_auth(request)
    if not emoji or len(emoji) > 50:
        raise HTTPException(status_code=400, detail="Invalid emoji")
    if emoji.startswith(":") and emoji.endswith(":"):
        _kw = emoji[1:-1]
        with get_session() as s:
            _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw, domain="").first()
            if not _emoji_row:
                _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw).first()
            if not _emoji_row or (_emoji_row.domain and _emoji_row.domain.strip()):
                raise HTTPException(status_code=400, detail="Remote emojis cannot be used as reactions")
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")

    def _do_react():
        try:
            with get_session() as s:
                react_post(s, user, post_id, emoji)
        except Exception:
            pass

    threading.Thread(target=_do_react, daemon=True).start()
    return {"ok": True}


@reactions_router.post("/posts/{post_id}/unreact")
def api_unreact_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

    def _do_unreact():
        try:
            with get_session() as s:
                unreact_post(s, user, post_id)
        except Exception:
            pass

    threading.Thread(target=_do_unreact, daemon=True).start()
    return {"ok": True}


@reactions_router.get("/posts/{post_id}/reaction-users")
def api_reaction_users(request: Request, post_id: int, emoji: str = ""):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        q = s.query(Like).filter(Like.post_id == post_id)
        if emoji == "★":
            q = q.filter((Like.reaction.is_(None)) | (Like.reaction == "★"))
        elif emoji:
            q = q.filter(Like.reaction == emoji)
        else:
            q = q.filter(Like.reaction.is_(None))
        like_rows = q.order_by(Like.id.desc()).limit(20).all()
        user_ids = list(dict.fromkeys(l.user_id for l in like_rows))
        from app.models import User
        users = s.query(User).filter(User.id.in_(user_ids)).all()
        from app.serializers import _user_json
        return {"users": [_user_json(u) for u in users]}
