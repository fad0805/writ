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


logger = logging.getLogger("writ.api.engagement")

from app.routes.api.interactions._common import _json_array_has_user

engagement_router = APIRouter()

# ── Post interactions (likes/boosts/bookmarks/polls/reactions/pins) —————————————————

@engagement_router.post("/posts/{post_id}/like")
def api_like_post(request: Request, background_tasks: BackgroundTasks, post_id: int, reaction: str = "★"):
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
                post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
                if not post:
                    return
                if not _can_view(post, user, s):
                    return
                existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                existing_notif = s.query(Notification).filter_by(
                    user_id=post.author_id, from_user_id=user.id, notification_type="like", post_id=post_id
                ).first() if post.author_id != user.id else None
                if not existing:
                    s.add(Like(user_id=user.id, post_id=post_id, reaction=reaction))
                    if post.author_id != user.id and not existing_notif:
                        _author_reactions = getattr(post.author, 'enable_reactions', True)
                        _notif_meta = {"reaction": reaction} if reaction and _author_reactions else {}
                        s.add(Notification(user_id=post.author_id, from_user_id=user.id, notification_type="like", post_id=post_id, metadata_json=json.dumps(_notif_meta) if _notif_meta else ""))
                    s.flush()
                    keep_id = s.query(Like.id).filter_by(user_id=user.id, post_id=post_id).order_by(Like.id.desc()).first()
                    if keep_id:
                        s.query(Like).filter(Like.user_id == user.id, Like.post_id == post_id, Like.id != keep_id[0]).delete(synchronize_session=False)
                    s.commit()
                    _reactions = {}
                    for _react, _cnt in s.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                        _reactions[_react or "★"] = _cnt
                    broadcast_reaction_update(post_id, _reactions)
                    if post.author_id != user.id:
                        broadcast_refresh_notifs(post.author_id)
                        send_push_to_user(post.author_id, "like", user.username, post_id)
                        broadcast_notif_sound(post.author_id)
                if post.author.is_remote and post.author.shared_inbox_url:
                    like_id = f"{BASE_URL}/likes/{uuid.uuid4()}"
                    like_rec = existing or s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                    if like_rec:
                        like_rec.ap_id = like_id
                        if reaction != "★":
                            like_rec.reaction = reaction
                        s.commit()
                    _react = reaction or "★"
                    is_custom = _react != "★"
                    activity_type = "EmojiReact" if is_custom else "Like"
                    like_activity = {
                        "@context": "https://www.w3.org/ns/activitystreams",
                        "id": like_id,
                        "type": activity_type,
                        "actor": user.actor_uri(),
                        "object": post.ap_id,
                        "to": [post.author.actor_uri()],
                        "cc": ["https://www.w3.org/ns/activitystreams#Public"],
                    }
                    if is_custom or _react:
                        like_activity["content"] = _react
                        like_activity["_misskey_reaction"] = _react
                    inbox = post.author.shared_inbox_url
                    try:
                        _post_to_inbox(inbox, like_activity, user)
                    except Exception:
                        pass
        except Exception:
            pass

    background_tasks.add_task(_do_like)
    return {"ok": True}


@engagement_router.post("/posts/{post_id}/unlike")
def api_unlike_post(request: Request, background_tasks: BackgroundTasks, post_id: int):
    user = require_active_auth(request)

    def _do_unlike():
        try:
            with get_session() as s:
                post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
                if not post:
                    return
                existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                like_id = existing.ap_id if existing and existing.ap_id else ""
                existing_reaction = existing.reaction if existing else None
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
                            "content": existing_reaction or "★",
                            "_misskey_reaction": existing_reaction or "★",
                        },
                    }
                    inbox = post.author.shared_inbox_url
                    try:
                        _post_to_inbox(inbox, undo, user)
                    except Exception:
                        pass
        except Exception:
            pass

    background_tasks.add_task(_do_unlike)
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
        if post.boost_of_id:
            post = s.query(Post).get(post.boost_of_id)
            post_id = post.id
        if post.author_id != user.id and post.visibility in ("followers", "mention"):
            raise HTTPException(status_code=403, detail="Cannot boost followers-only or mention-only posts from other users")
        existing = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
        existing_notif = s.query(Notification).filter_by(
            user_id=post.author_id, from_user_id=user.id, notification_type="boost", post_id=post_id
        ).first() if post.author_id != user.id else None
        if not existing:
            s.add(Boost(user_id=user.id, post_id=post_id))
            boost_post = Post(
                author_id=user.id,
                content="",
                boost_of_id=post_id,
                visibility=post.visibility or "public",
            )
            s.add(boost_post)
            if post.author_id != user.id and not existing_notif:
                s.add(Notification(user_id=post.author_id, from_user_id=user.id, notification_type="boost", post_id=post_id))
            s.commit()
            try:
                _a = post.author
                _author_json = _user_json(_a)
                _boosted_json = _user_json(user)
                _og = {
                    "id": post.id,
                    "number": post.number or "",
                    "content": post.content,
                    "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": _fmt_dt(post.created_at),
                    "author": _author_json,
                    "likes_count": 0,
                    "boosts_count": s.query(Boost).filter_by(post_id=post_id).count(),
                    "replies_count": post.replies_count or 0,
                    "liked": False, "boosted": True, "bookmarked": False,
                    "is_mine": True, "is_dm": False,
                    "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "",
                    "reply_context": None,
                    "boosted_by": _boosted_json,
                    "media_attachments": (post.media_attachments or []) if hasattr(post, 'media_attachments') else [],
                    "poll_data": None, "my_vote": None,
                    "reactions": {}, "my_reaction": None,
                    "mentioned_user_ids": [], "mentioned_handles": [],
                    "link_preview": None,
                    "_emojis": [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(s)],
                }
                _boost_user_id = user.id
                _boost_post_id = post_id
                def _safe_broadcast_boost_pointer():
                    with get_session() as _s:
                        if _s.query(Boost).filter_by(user_id=_boost_user_id, post_id=_boost_post_id).first():
                            _broadcast_timeline(_og, _boost_user_id, post.visibility or "public", False)
                threading.Thread(target=_safe_broadcast_boost_pointer, daemon=True).start()
            except Exception as e:
                logger.error("Failed to broadcast boost stream: %s", e, exc_info=True)
            try:
                broadcast_post({
                    "id": post.id, "type": "update",
                    "boosts_count": s.query(Boost).filter_by(post_id=post_id).count(),
                    "boosted_by": _user_json(user),
                }, post.author_id, post.visibility or "public", False)
            except Exception as e:
                logger.error("Failed to broadcast boost update: %s", e, exc_info=True)
            if post.author_id != user.id:
                broadcast_refresh_notifs(post.author_id)
                send_push_to_user(post.author_id, "boost", user.username, post_id)
                broadcast_notif_sound(post.author_id)

            announce_id = f"{BASE_URL}/boosts/{uuid.uuid4()}"

            if post.author.is_remote and post.author.shared_inbox_url:
                boost_rec = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
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
                "cc": [
                    post.author.actor_uri(),
                    f'{BASE_URL}/users/{user.username}/followers'
                ],
            }

            if post.author.is_remote and post.author.shared_inbox_url:
                try:
                    threading.Thread(target=_post_to_inbox, args=(inbox, announce, user), daemon=True).start()
                except Exception as e:
                    logger.error("Failed to send boost to author inbox: %s", e, exc_info=True)

            try:
                followers = s.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == user.id).all()
                sent_inboxes = set()
                for follower in followers:
                    if follower.is_remote and (follower.shared_inbox_url or follower.inbox_url):
                        inbox = follower.shared_inbox_url or follower.inbox_url
                        if inbox not in sent_inboxes:
                            sent_inboxes.add(inbox)
                            try:
                                threading.Thread(target=_post_to_inbox, args=(inbox, announce, user), daemon=True).start()
                            except Exception as e:
                                logger.error("Failed to fan-out boost to inbox %s: %s", inbox, e, exc_info=True)
            except Exception as e:
                logger.error("Failed to query followers for boost fan-out: %s", e, exc_info=True)

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
        if post.boost_of_id:
            post = s.query(Post).get(post.boost_of_id)
            post_id = post.id
        existing = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
        announce_id = existing.ap_id if existing and existing.ap_id else ""
        if existing:
            s.delete(existing)
            s.query(Post).filter_by(author_id=user.id, boost_of_id=post_id).delete()
            s.query(Notification).filter_by(
                from_user_id=user.id, notification_type="boost", post_id=post_id
            ).delete()
            remaining = s.query(Boost).filter_by(post_id=post_id).count()
            s.commit()
            if post.author_id != user.id:
                broadcast_refresh_notifs(post.author_id)
            try:
                broadcast_post({
                    "id": post_id, "type": "update",
                    "boosts_count": remaining,
                    "boosted_by": None,
                }, post.author_id, post.visibility or "public", False)
            except Exception as e:
                logger.error("Failed to broadcast unboost update: %s", e, exc_info=True)

            undo_id = f"{BASE_URL}/boosts/{uuid.uuid4()}#undo"
            target_announce_id = announce_id or f"{BASE_URL}/boosts/{uuid.uuid4()}"
            undo = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": undo_id,
                "type": "Undo",
                "actor": user.actor_uri(),
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [
                    post.author.actor_uri(),
                    f'{BASE_URL}/users/{user.username}/followers'
                ],
                "object": {
                    "id": target_announce_id,
                    "type": "Announce",
                    "actor": user.actor_uri(),
                    "object": post.ap_id,
                },
            }
            if post.author.is_remote and post.author.shared_inbox_url:
                try:
                    threading.Thread(target=_post_to_inbox, args=(post.author.shared_inbox_url, undo, user), daemon=True).start()
                except Exception as e:
                    logger.error("Failed to send unboost to author inbox: %s", e, exc_info=True)
            try:
                followers = s.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == user.id).all()
                sent_inboxes = set()
                for follower in followers:
                    if follower.is_remote and (follower.shared_inbox_url or follower.inbox_url):
                        inbox = follower.shared_inbox_url or follower.inbox_url
                        if inbox not in sent_inboxes:
                            sent_inboxes.add(inbox)
                            try:
                                _post_to_inbox(inbox, undo, user)
                            except Exception as e:
                                logger.error("Failed to fan-out unboost to inbox %s: %s", inbox, e, exc_info=True)
            except Exception as e:
                logger.error("Failed to query followers for unboost fan-out: %s", e, exc_info=True)
    return {"ok": True}

