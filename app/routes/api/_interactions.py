"""Interaction endpoints — follow, DM, notification, mute/block, like, boost, bookmark, vote, react, pin."""
import json
import re
import time
import logging
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from uuid import uuid4
from fastapi import APIRouter, Request, Form, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import or_, and_, func, String, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, ProfileNote, UserMute, UserBlock, SeriesMute, KeywordMute, CustomEmoji, ServerSetting
from app.serializers import _user_json, _post_json
from app.config.settings import BASE_URL
from app.core.activitypub import _post_to_inbox, _resolve_actor, _send_accept, _send_reject
from app.core.push import send_push_to_user
from app.core.broadcast import broadcast_post
from app.core.timeline_stream import broadcast_refresh_notifs, add_notif_stream, remove_notif_stream, broadcast_notif_sound, broadcast_reaction_update, broadcast_delete
from app.db.database import get_session
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.routes.api._core import _ap_fetch
from app.core.interactions import _can_view
from app.utils.datetime import _fmt_dt
from app.utils.emoji import _emoji_url

logger = logging.getLogger("writ.api.interactions")


def _json_array_has_user(column, user_id):
    """JSON 배열 컬럼에 user_id가 정확히 포함되어 있는지 확인"""
    if isinstance(column.type, postgresql.JSONB):
        return column.cast(JSONB).op('@>')(func.json_build_array(user_id).cast(JSONB))
    else:
        # SQLite fallback: cast to text and check containment via LIKE
        return column.cast(String).like(f'%{user_id}%')


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


interactions_router = APIRouter()


@interactions_router.post("/users/{username}/follow")
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
                    "id": f"{BASE_URL}/activities/follow/{uuid4()}",
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


@interactions_router.post("/users/{username}/approve-follow")
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

@interactions_router.post("/users/{username}/remove-follower")
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

@interactions_router.get("/follow-requests")
def api_list_follow_requests(request: Request):
    user = require_auth(request)
    with get_session() as s:
        pending = s.query(Follow).filter_by(following_id=user.id, accepted=False).all()
        return {"requests": [{"id": f.id, "user": _user_json(f.follower)} for f in pending]}


@interactions_router.post("/users/{username}/reject-follow")
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

@interactions_router.post("/users/{username}/unfollow")
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


@interactions_router.post("/users/{username}/toggle-notify")
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


@interactions_router.get("/users/{username}/followers")
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


@interactions_router.get("/users/{username}/following")
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


@interactions_router.get("/direct/conversation/{other_id}")
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


@interactions_router.get("/notifications/direct-threads")
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


@interactions_router.get("/notifications")
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
                    _mentioned_users_map=_mentioned_users_map,
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

    return {"notifications": result, "has_more": has_more, "total": 0}


@interactions_router.get("/notifications/stream")
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

@interactions_router.get("/notifications/unread-count")
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


@interactions_router.get("/profile-notes/{target_username}")
def api_get_profile_note(request: Request, target_username: str):
    user = require_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=target_username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        note = s.query(ProfileNote).filter_by(user_id=user.id, target_user_id=target.id).first()
        return {"content": note.content if note else ""}


@interactions_router.post("/profile-notes/{target_username}")
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


# ── User mute/block ──
@interactions_router.get("/mutes/users")
def api_list_user_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(UserMute).filter_by(user_id=user.id).order_by(UserMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "target_user_id": m.target_user_id, "username": m.target_user.username, "display_name": m.target_user.display_name, "avatar": m.target_user.profile_image or "", "duration": m.duration, "hide_notifications": m.hide_notifications, "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@interactions_router.post("/mutes/users/{target_user_id}")
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


@interactions_router.delete("/mutes/users/{target_user_id}")
def api_unmute_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(UserMute).filter_by(user_id=user.id, target_user_id=target_user_id).delete()
        s.commit()
    return {"ok": True}


@interactions_router.get("/blocks/users")
def api_list_user_blocks(request: Request):
    user = require_auth(request)
    with get_session() as s:
        blocks = s.query(UserBlock).filter_by(user_id=user.id).order_by(UserBlock.created_at.desc()).all()
        return {"blocks": [{"id": b.id, "target_user_id": b.target_user_id, "username": b.target_user.username, "display_name": b.target_user.display_name, "avatar": b.target_user.profile_image or "", "created_at": _fmt_dt(b.created_at)} for b in blocks]}


@interactions_router.post("/blocks/users/{target_user_id}")
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


@interactions_router.delete("/blocks/users/{target_user_id}")
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
@interactions_router.get("/mutes/series")
def api_list_series_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(SeriesMute).filter_by(user_id=user.id).order_by(SeriesMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "novel_id": m.novel_id, "title": m.novel.title, "cover_image": m.novel.cover_image or "", "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@interactions_router.post("/mutes/series/{novel_id}")
def api_mute_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(SeriesMute).filter_by(user_id=user.id, novel_id=novel_id).first()
        if existing:
            return {"ok": True}
        s.add(SeriesMute(user_id=user.id, novel_id=novel_id))
        s.commit()
    return {"ok": True}


@interactions_router.delete("/mutes/series/{novel_id}")
def api_unmute_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(SeriesMute).filter_by(user_id=user.id, novel_id=novel_id).delete()
        s.commit()
    return {"ok": True}


# ── Keyword mute ──
@interactions_router.get("/mutes/keywords")
def api_list_keyword_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(KeywordMute).filter_by(user_id=user.id).order_by(KeywordMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "keyword": m.keyword, "name": m.name or "", "mode": m.mode, "is_regex": m.is_regex, "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@interactions_router.post("/mutes/keywords")
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


@interactions_router.delete("/mutes/keywords/{mute_id}")
def api_remove_keyword_mute(request: Request, mute_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(KeywordMute).filter_by(id=mute_id, user_id=user.id).delete()
        s.commit()
    return {"ok": True}


# ── Post interactions (likes/boosts/bookmarks/polls/reactions/pins) —————————————————

@interactions_router.post("/posts/{post_id}/like")
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


@interactions_router.post("/posts/{post_id}/unlike")
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


@interactions_router.post("/posts/{post_id}/boost")
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
                _boosts_count = s.query(Boost).filter_by(post_id=post_id).count()
                broadcast_post({
                    "id": post.id, "type": "update",
                    "boosts_count": _boosts_count,
                }, post.author_id, post.visibility or "public")
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


@interactions_router.post("/posts/{post_id}/bookmark")
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


@interactions_router.post("/posts/{post_id}/unbookmark")
def api_unbookmark_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(Bookmark).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            s.delete(existing)
            s.commit()
    return {"ok": True}


@interactions_router.get("/bookmarks")
def api_bookmarks(request: Request, limit: int = Query(20), offset: int = Query(0)):
    user = require_active_auth(request)
    with get_session() as s:
        raw = s.query(Bookmark).filter_by(user_id=user.id).order_by(desc(Bookmark.created_at)).offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        posts = [_post_json(b.post, s, user) for b in raw[:limit] if b.post and not b.post.is_deleted and _can_view(b.post, user, s)]
        return {"posts": posts, "has_more": has_more}


@interactions_router.get("/favorites")
def api_favorites(request: Request, limit: int = Query(10), offset: int = Query(0)):
    limit = min(limit, 20)
    user = require_active_auth(request)
    with get_session() as s:
        raw = s.query(Like).filter_by(user_id=user.id).order_by(desc(Like.created_at)).offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        posts = [_post_json(l.post, s, user) for l in raw[:limit] if l.post and not l.post.is_deleted and _can_view(l.post, user, s)]
        return {"posts": posts, "has_more": has_more}


@interactions_router.post("/posts/{post_id}/unboost")
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
            _bp = s.query(Post.id).filter_by(author_id=user.id, boost_of_id=post_id).first()
            _bp_id = _bp[0] if _bp else None
            s.delete(existing)
            s.query(Post).filter_by(author_id=user.id, boost_of_id=post_id).delete()
            s.query(Notification).filter_by(
                from_user_id=user.id, notification_type="boost", post_id=post_id
            ).delete()
            remaining = s.query(Boost).filter_by(post_id=post_id).count()
            s.commit()
            if _bp_id:
                try:
                    broadcast_delete(_bp_id)
                except Exception as e:
                    logger.error("Failed to broadcast boost pointer delete: %s", e, exc_info=True)
            if post.author_id != user.id:
                broadcast_refresh_notifs(post.author_id)
            try:
                broadcast_post({
                    "id": post_id, "type": "update",
                    "boosts_count": remaining,
                    "boosted_by": [],
                }, post.author_id, post.visibility or "public")
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


@interactions_router.post("/posts/{post_id}/react")
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


@interactions_router.post("/posts/{post_id}/unreact")
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


@interactions_router.get("/posts/{post_id}/reaction-users")
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
        if not user_ids:
            return {"users": []}
        users = {u.id: u for u in s.query(User).filter(User.id.in_(user_ids)).all()}
        return {"users": [_user_json(users[uid]) for uid in user_ids if uid in users]}


@interactions_router.post("/posts/{post_id}/vote")
def api_vote_post(request: Request, post_id: int, option: int = Form(...)):
    user = require_active_auth(request)
    remote_vote_data = None
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        options = post.poll_data.get("options", [])
        if option < 0 or option >= len(options):
            raise HTTPException(status_code=400, detail="Invalid option")
        expires_at = post.poll_data.get("expires_at")
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
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
            s.add(
                Vote(
                    user_id=user.id,
                    post_id=post_id,
                    option_index=option,
                    expires_at=post.poll_data.get("expires_at")
                )
            )
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


@interactions_router.post("/posts/{post_id}/unvote")
def api_unvote_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
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


@interactions_router.post("/posts/{post_id}/refresh-poll")
def api_refresh_poll(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        if not post.ap_id:
            raise HTTPException(status_code=400, detail="Local poll has nothing to refresh")
    remote_data = _ap_fetch(post.ap_id, user)
    if not remote_data:
        raise HTTPException(status_code=502, detail="Failed to fetch remote poll")
    obj = remote_data.get("object", remote_data) if isinstance(remote_data, dict) else {}
    if not isinstance(obj, dict):
        raise HTTPException(status_code=502, detail="Invalid remote response")

    one_of = obj.get("oneOf") or obj.get("anyOf") or []
    if not isinstance(one_of, list) or not one_of:
        raise HTTPException(status_code=502, detail="Remote object has no poll data")

    new_options = []
    for opt in one_of:
        if isinstance(opt, dict) and opt.get("name"):
            replies = opt.get("replies", {})
            votes_count = 0
            if isinstance(replies, dict):
                votes_count = replies.get("totalItems", 0)
            new_options.append({"text": opt["name"], "votes_count": votes_count})

    if not new_options:
        raise HTTPException(status_code=502, detail="No valid poll options found")

    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post not found")
        old_options = post.poll_data.get("options", [])
        text_to_old = {o.get("text", ""): o for o in old_options}
        for new_opt in new_options:
            old = text_to_old.get(new_opt["text"])
            if old:
                new_opt["votes_count"] = max(new_opt.get("votes_count", 0), old.get("votes_count", 0))

        new_expires = obj.get("endTime") or post.poll_data.get("expires_at", "")
        post.poll_data = {
            "options": new_options,
            "expires_at": new_expires,
        }
        s.commit()
        s.expire_all()

        post = s.query(Post).filter_by(id=post_id).first()
        updated = _post_json(post, s, user)

    return {"ok": True, "post": updated}


@interactions_router.post("/pin/post/{post_id}")
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


@interactions_router.post("/unpin/post/{post_id}")
def api_unpin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            pinned.remove(post_id)
            s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
            s.commit()
    return {"ok": True}


__all__ = ["interactions_router"]
