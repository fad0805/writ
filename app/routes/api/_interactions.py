"""Follow, DM, notification, and mutes/blocks endpoints extracted from _core.py."""
import json
import re
import time
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from uuid import uuid4
from fastapi import APIRouter, Request, Form, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import or_, and_, func, String, desc, select
from sqlalchemy.orm import selectinload, Session, joinedload
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, ProfileNote, UserMute, UserBlock, SeriesMute, KeywordMute, PushSubscription
from app.serializers import _user_json, _post_json
from app.config.settings import BASE_URL, MAX_POST_LENGTH
from app.core.activitypub import _send_delete_post, _post_to_inbox, _resolve_actor, _send_accept, _send_reject
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_refresh_notifs, add_notif_stream, remove_notif_stream, broadcast_notif_sound
from app.db.database import get_session, get_db
from app.db.mention_resolver import resolve_handles_to_ids
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.utils.datetime import _fmt_dt
from app.utils.emoji import _emoji_url
from app.utils.filter import _timeline_filter
from app.utils.storage import get_storage

from app.routes.api._core import _can_view

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


__all__ = ["interactions_router"]
