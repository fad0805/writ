"""Interaction endpoints — follow, DM, notification, mute/block, like, boost, bookmark, vote, react, pin."""
import json
import re
import time
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, and_, func, desc
from sqlalchemy.orm import selectinload

from app.models import User, Post, Like, Boost, Vote, Bookmark, Notification, ProfileNote
from app.serializers import _user_json, _post_json
from app.core.timeline_stream import add_notif_stream, remove_notif_stream
from app.db.database import get_session
from app.core.auth import require_auth, get_current_user
from app.utils.datetime import _fmt_dt

from app.core.visibility import _can_view
from app.routes.api.interactions._common import _json_array_has_user, _generate_poll_end_notifications

logger = logging.getLogger("writ.api.notify")

notify_router = APIRouter()


@notify_router.get("/direct/conversation/{other_id}")
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


@notify_router.get("/notifications/direct-threads")
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


@notify_router.get("/notifications")
def api_notifications(request: Request, filter_type: str = Query(""), limit: int = Query(20, le=100), offset: int = Query(0), mark_read: bool = Query(True)):
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

        if user and notif_post_ids:
            _liked_ids = {l.post_id for l in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(notif_post_ids)).all()}
            _boosted_ids = {b.post_id for b in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(notif_post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(notif_post_ids)).all()}

            for v in s.query(Vote.post_id, Vote.option_index).filter(Vote.user_id == user.id, Vote.post_id.in_(notif_post_ids)).all():
                _vote_map[v.post_id] = v.option_index

            for l in s.query(Like.post_id, Like.reaction).filter(Like.user_id == user.id, Like.post_id.in_(notif_post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[l.post_id] = l.reaction

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
                if not meta.get("reaction") and n.post and n.from_user_id:
                    _like_row = s.query(Like.reaction).filter(Like.user_id == n.from_user_id, Like.post_id == n.post_id).first()
                    if _like_row and _like_row[0]:
                        meta = {"reaction": _like_row[0]}
                    else:
                        meta = {"reaction": "★"}
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
                    _mentioned_users_map=_mentioned_users_map,
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

    return {"notifications": result, "has_more": has_more, "total": 0}


@notify_router.get("/notifications/stream")
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


_unread_cache: dict[int, tuple[int, float]] = {}
_UNREAD_CACHE_TTL = 5.0

@notify_router.get("/notifications/unread-count")
def api_unread_count(request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Not authenticated"}, 401
    now = time.time()
    cached = _unread_cache.get(user.id)
    if cached and now - cached[1] < _UNREAD_CACHE_TTL:
        return {"count": cached[0]}
    with get_session() as s:
        count = s.query(Notification.id).filter_by(user_id=user.id, is_read=False).count()
    _unread_cache[user.id] = (count, now)
    return {"count": count}


@notify_router.get("/profile-notes/{target_username}")
def api_get_profile_note(request: Request, target_username: str):
    user = require_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=target_username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        note = s.query(ProfileNote).filter_by(user_id=user.id, target_user_id=target.id).first()
        return {"content": note.content if note else ""}


@notify_router.post("/profile-notes/{target_username}")
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
