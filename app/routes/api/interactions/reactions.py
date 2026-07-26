"""Interaction endpoints — follow, DM, notification, mute/block, like, boost, bookmark, vote, react, pin."""
import json
import re
import time
import logging
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import uuid
from uuid import uuid4
from fastapi import APIRouter, Request, Form, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import or_, and_, func, String, desc, select
from sqlalchemy.orm import selectinload, Session, joinedload
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, ProfileNote, UserMute, UserBlock, SeriesMute, KeywordMute, PushSubscription, CustomEmoji, ServerSetting
from app.serializers import _user_json, _post_json
from app.config.settings import BASE_URL, MAX_POST_LENGTH
from app.core.activitypub import _send_delete_post, _post_to_inbox, _resolve_actor, _send_accept, _send_reject
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_refresh_notifs, add_notif_stream, remove_notif_stream, broadcast_notif_sound, broadcast_reaction_update, broadcast_post
from app.db.database import get_session, get_db
from app.db.mention_resolver import resolve_handles_to_ids
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.utils.datetime import _fmt_dt
from app.utils.emoji import _emoji_url, _load_emojis
from app.utils.filter import _timeline_filter
from app.utils.storage import get_storage

from app.routes.api._core import _can_view, _ap_fetch, _check_fetch_domain_allowed
from app.routes.api._feed import _broadcast_timeline


logger = logging.getLogger("writ.api.reactions")

from app.routes.api.interactions._common import _json_array_has_user

reactions_router = APIRouter()


@reactions_router.post("/posts/{post_id}/react")
def api_react_post(request: Request, background_tasks: BackgroundTasks, post_id: int, emoji: str = Form(...)):
    user = require_active_auth(request)
    with get_session() as s:
        settings = ServerSetting.get(s)
        if not emoji or len(emoji) > 50:
            raise HTTPException(status_code=400, detail="Invalid emoji")
        if emoji.startswith(":") and emoji.endswith(":"):
            _kw = emoji[1:-1]
            _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw, domain="").first()
            if not _emoji_row:
                _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw).first()
            if not _emoji_row or (_emoji_row.domain and _emoji_row.domain.strip()):
                raise HTTPException(status_code=400, detail="Remote emojis cannot be used as reactions")
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        reactions_disabled = not settings.enable_reactions or not getattr(post.author, 'enable_reactions', True)
        final_emoji = emoji if not reactions_disabled else None
        existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        old_reaction = existing.reaction if existing else None
        is_new = existing is None
        post_author_id = post.author_id
        post_ap_id = post.ap_id
        post_author_is_remote = post.author.is_remote
        post_author_shared_inbox = post.author.shared_inbox_url if post_author_is_remote else None
        post_author_actor = post.author.actor_uri() if post_author_is_remote else None
        post_author_enable_reactions = getattr(post.author, 'enable_reactions', True)

    def _do_react():
        try:
            with get_session() as s:
                post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
                if not post:
                    return
                existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                existing_notif = s.query(Notification).filter_by(
                    user_id=post_author_id, from_user_id=user.id, notification_type="like", post_id=post_id
                ).first() if post_author_id != user.id else None
                if existing:
                    existing.reaction = final_emoji
                    if post_author_id != user.id and existing_notif:
                        _notif_meta = {"reaction": final_emoji} if final_emoji and post_author_enable_reactions else {}
                        existing_notif.metadata_json = json.dumps(_notif_meta) if _notif_meta else ""
                else:
                    s.add(Like(user_id=user.id, post_id=post_id, reaction=final_emoji))
                    if post_author_id != user.id and not existing_notif:
                        _notif_meta = {"reaction": final_emoji} if final_emoji and post_author_enable_reactions else {}
                        s.add(Notification(user_id=post_author_id, from_user_id=user.id, notification_type="like", post_id=post_id, metadata_json=json.dumps(_notif_meta) if _notif_meta else ""))
                s.flush()
                keep_id = s.query(Like.id).filter_by(user_id=user.id, post_id=post_id).order_by(Like.id.desc()).first()
                if keep_id:
                    s.query(Like).filter(Like.user_id == user.id, Like.post_id == post_id, Like.id != keep_id[0]).delete(synchronize_session=False)
                s.commit()
                _reactions = {}
                for _react, _cnt in s.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                    _reactions[_react or "★"] = _cnt
                broadcast_reaction_update(post_id, _reactions)
                if post_author_id != user.id:
                    broadcast_refresh_notifs(post_author_id)
                if post_author_is_remote and post_author_shared_inbox:
                    _tag = []
                    if emoji.startswith(":") and emoji.endswith(":"):
                        _kw = emoji[1:-1]
                        _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw, domain="").first()
                        if not _emoji_row:
                            _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw).first()
                        if _emoji_row and _emoji_row.file_name:
                            _emoji_img = _emoji_url(_emoji_row.file_name, _emoji_row.domain or "", _emoji_row.category or "")
                            if not _emoji_img.startswith("http"):
                                _emoji_img = f"{BASE_URL}{_emoji_img}"
                        else:
                            _emoji_img = ""
                        if _emoji_img:
                            _tag = [{"type": "Emoji", "id": f"{BASE_URL}/emojis/{_kw}", "name": emoji, "icon": {"type": "Image", "mediaType": "image/png", "url": _emoji_img}}]
                    like_activity = {
                        "@context": "https://www.w3.org/ns/activitystreams",
                        "id": f"{BASE_URL}/likes/{uuid.uuid4()}",
                        "type": "Like",
                        "actor": user.actor_uri(),
                        "object": post_ap_id,
                        "content": emoji,
                        "_misskey_reaction": emoji,
                    }
                    if _tag:
                        like_activity["tag"] = _tag
                    if is_new or old_reaction != emoji:
                        try:
                            _post_to_inbox(post_author_shared_inbox, like_activity, user)
                        except Exception:
                            pass
        except Exception:
            pass

    background_tasks.add_task(_do_react)
    return {"ok": True}


@reactions_router.post("/posts/{post_id}/unreact")
def api_unreact_post(request: Request, background_tasks: BackgroundTasks, post_id: int):
    user = require_active_auth(request)
    existing_reaction = None
    post_ap_id = ""
    post_author_is_remote = False
    post_author_shared_inbox = None
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        existing_reaction = existing.reaction if existing else None
        post_ap_id = post.ap_id
        post_author_is_remote = post.author.is_remote
        post_author_shared_inbox = post.author.shared_inbox_url if post_author_is_remote else None

    def _do_unreact():
        try:
            with get_session() as s:
                post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
                if not post:
                    return
                existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                if existing:
                    s.delete(existing)
                    s.query(Notification).filter_by(
                        from_user_id=user.id, notification_type="like", post_id=post_id
                    ).delete()
                    s.commit()
                    _reactions = {}
                    for _react, _cnt in s.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                        _reactions[_react or "★"] = _cnt
                    broadcast_reaction_update(post_id, _reactions)
                    broadcast_refresh_notifs(post.author_id)
                    if post_author_is_remote and post_author_shared_inbox:
                        undo = {
                            "@context": "https://www.w3.org/ns/activitystreams",
                            "id": f"{BASE_URL}/likes/{uuid.uuid4()}#undo",
                            "type": "Undo",
                            "actor": user.actor_uri(),
                            "object": {
                                "id": f"{BASE_URL}/likes/{uuid.uuid4()}",
                                "type": "Like",
                                "actor": user.actor_uri(),
                                "object": post_ap_id,
                                "content": existing_reaction or "★",
                                "_misskey_reaction": existing_reaction or "★",
                            },
                        }
                        try:
                            _post_to_inbox(post_author_shared_inbox, undo, user)
                        except Exception:
                            pass
        except Exception:
            pass

    background_tasks.add_task(_do_unreact)
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
