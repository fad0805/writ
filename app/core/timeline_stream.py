import json
import asyncio
import logging

from sqlalchemy import func

from app.db.database import get_session
from app.models import Post, Follow, User, Boost, Notification
from app.utils.filter import should_deliver_post, _load_user_filters

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None
_streams: dict[int, dict] = {}
_counter = 0

def _set_loop():
    global _main_loop
    if _main_loop is None:
        try:
            _main_loop = asyncio.get_running_loop()
        except RuntimeError:
            _main_loop = asyncio.get_event_loop()

def _enqueue(queue: asyncio.Queue, item: str):
    if _main_loop and _main_loop.is_running():
        def _put():
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass
        _main_loop.call_soon_threadsafe(_put)
    else:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass

def add_stream(user_id: int, tl_type: str) -> tuple[int, asyncio.Queue]:
    global _counter
    _set_loop()
    _counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _streams[_counter] = {"queue": q, "user_id": user_id, "tl_type": tl_type}
    return _counter, q


def remove_stream(sid: int):
    _streams.pop(sid, None)


def broadcast_post(post_json: dict, post_author_id: int, post_visibility: str, mentioned_ids = None):
    if post_visibility not in (
        "public", "home", "followers", "mention") or not _streams:
        return

    try:
        # content가 dict 타입으로 잘못 유입되었는지 방어 코드 추가
        if isinstance(post_json.get("content"), dict):
            # dict 형태라면 특정 언어 코드를 가져오거나 문자열로 강제 치환
            content_dict = post_json["content"]
            post_json["content"] = content_dict.get("html") or content_dict.get("text") or str(content_dict)

        if not post_json.get("author") and post_json.get("type") != "update":
            return

        payload = json.dumps(post_json, default=str)
        mentioned_ids = post_json.get("mentioned_user_ids") or []
        # Extract parent author ID from reply_context
        parent_author_id = None
        reply_ctx = post_json.get("reply_context")
        if reply_ctx and isinstance(reply_ctx, dict):
            parent_author = reply_ctx.get("author")
            if parent_author:
                parent_author_id = parent_author.get("id")

        with get_session() as s:
            # If not in JSON, look up from DB
            _pid = post_json.get("id")
            _is_reply = bool(post_json.get("in_reply_to_id") or post_json.get("in_reply_to_ap_id") or reply_ctx)
            if not _is_reply and _pid:
                try:
                    _db_post = s.query(Post).filter_by(id=_pid).first()
                    if _db_post and _db_post.in_reply_to_id:
                        _is_reply = True
                        _parent = s.query(Post).filter_by(id=_db_post.in_reply_to_id).first()
                        if _parent:
                            parent_author_id = _parent.author_id
                except Exception:
                    pass

            post_id_for_boost = post_json.get("id")
            follower_ids = {f.follower_id for f in s.query(Follow).filter_by(
                following_id=post_author_id, accepted=True
            ).all()}
            booster_ids = {b.user_id for b in s.query(Boost).filter_by(post_id=post_id_for_boost).all()}
            # 팔로워 공개 글은 부스트한 사람의 팔로워에게 전파하지 않음
            if booster_ids and post_visibility != "followers":
                for bf in s.query(Follow).filter(
                    Follow.following_id.in_(booster_ids), Follow.accepted == True
                ).all():
                    follower_ids.add(bf.follower_id)
            author = s.query(User).get(post_author_id)
            author_is_local = author.is_remote == False if author else False

            # Pre-load following lists for home/social timeline streams
            home_uids = {info["user_id"] for info in _streams.values() if info.get("tl_type") in ("home", "social")}
            all_stream_uids = {info["user_id"] for info in _streams.values()}
            stream_users = {}
            if all_stream_uids:
                for u in s.query(User).filter(User.id.in_(all_stream_uids)).all():
                    stream_users[u.id] = u
            home_follows = {}
            if home_uids:
                for f in s.query(Follow).filter(Follow.follower_id.in_(home_uids), Follow.accepted == True).all():
                    home_follows.setdefault(f.follower_id, set()).add(f.following_id)

            # Pre-load Post ORM object and per-user filter context for home/social
            _db_post = s.query(Post).filter_by(id=post_json.get("id")).first()
            # Boost pointer: use actual boost pointer Post for author-based filtering (block/mute against booster)
            _boost_pointer_id = post_json.get("_boost_pointer_id")
            if _boost_pointer_id:
                _bp = s.query(Post).filter_by(id=_boost_pointer_id).first()
                if _bp and not _bp.is_deleted:
                    _db_post = _bp
            _filter_cache: dict[int, dict | None] = {}

            for _, info in list(_streams.items()):
                uid = info["user_id"]
                tl = info["tl_type"]
                if post_json.get("type") != "update" and not _should_deliver_fast(uid, tl, post_author_id, post_visibility, follower_ids, booster_ids, author_is_local, mentioned_ids):
                    continue
                # Home/social: use unified filter (mention, reply, mute/block, keyword)
                if tl in ("home", "social") and post_visibility != "mention":
                    if uid not in _filter_cache:
                        _filter_cache[uid] = _load_user_filters(s, stream_users.get(uid))
                    viewer = stream_users.get(uid)
                    following_set = home_follows.get(uid, set()) | {uid}
                    _is_boosted = bool(booster_ids)
                    if _db_post and not should_deliver_post(_db_post, s, viewer, tl, following_set, _filter_cache[uid], is_boosted=_is_boosted):
                        continue
                _enqueue(info["queue"], payload)
    except Exception as e:
        logger.error("BROADCAST_POST ERROR", exc_info=True)


def _broadcast_timeline(post_json, author_id, visibility):
    try:
        broadcast_post(post_json, author_id, visibility)
    except Exception as e:
        logger.error("Failed to broadcast timeline: %s", e, exc_info=True)


_notif_streams: dict[int, dict] = {}
_notif_counter = 0

def add_notif_stream(user_id: int = 0) -> tuple[int, asyncio.Queue]:
    global _notif_counter
    _set_loop()
    _notif_counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _notif_streams[_notif_counter] = {"queue": q, "user_id": user_id}
    print(f"[SSE] add_notif_stream: sid={_notif_counter} uid={user_id} total={len(_notif_streams)}", flush=True)
    return _notif_counter, q

def remove_notif_stream(sid: int):
    print(f"[SSE] remove_notif_stream: sid={sid} remaining={len(_notif_streams) - 1}", flush=True)
    _notif_streams.pop(sid, None)

def broadcast_notif(payload: str, target_user_id: int = 0):
    print(f"[SSE] broadcast_notif: target={target_user_id} streams={len(_notif_streams)}", flush=True)
    for info in list(_notif_streams.values()):
        if target_user_id == 0 or info.get("user_id") == target_user_id:
            _enqueue(info["queue"], payload)

def broadcast_refresh_notifs(target_user_id: int = 0):
    print(f"[SSE] broadcast_refresh_notifs target={target_user_id}", flush=True)
    broadcast_notif("refresh", target_user_id)
    if target_user_id != 0:
        try:
            with get_session() as s:
                cnt = s.query(func.count(Notification.id)).filter_by(user_id=target_user_id, is_read=False).scalar()
            broadcast_notif(json.dumps({"event": "notif", "unread": cnt}), target_user_id)
        except Exception:
            broadcast_notif(json.dumps({"event": "notif"}), target_user_id)

def broadcast_notif_sound(target_user_id: int):
    """Send a JSON event that triggers notification sound in the browser."""
    try:
        with get_session() as s:
            cnt = s.query(func.count(Notification.id)).filter_by(user_id=target_user_id, is_read=False).scalar()
        broadcast_notif(json.dumps({"event": "notif", "unread": cnt, "sound": True}), target_user_id)
    except Exception:
        broadcast_notif(json.dumps({"event": "notif", "sound": True}), target_user_id)


_post_streams: dict[int, dict] = {}
_post_counter = 0


def broadcast_delete(post_id: int):
    """Broadcast a delete event to all connected timeline streams and post streams."""
    payload = json.dumps({"type": "delete", "id": post_id})
    for info in list(_streams.values()):
        _enqueue(info["queue"], payload)
    for info in list(_post_streams.values()):
        if info["post_id"] == post_id:
            _enqueue(info["queue"], payload)


def add_post_stream(post_id: int) -> tuple[int, asyncio.Queue]:
    global _post_counter
    _set_loop()
    _post_counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _post_streams[_post_counter] = {"queue": q, "post_id": post_id}
    return _post_counter, q

def remove_post_stream(sid: int):
    _post_streams.pop(sid, None)


def broadcast_reaction_update(post_id: int, reactions: dict):
    """Broadcast updated reactions dict for a post to all connected timeline streams and post streams."""
    payload = json.dumps({"type": "update", "id": post_id, "reactions": reactions}, default=str)
    for info in list(_streams.values()):
        _enqueue(info["queue"], payload)
    for info in list(_post_streams.values()):
        if info["post_id"] == post_id:
            _enqueue(info["queue"], payload)


def _should_deliver_fast(user_id: int, tl_type: str, author_id: int, visibility: str,
                         follower_ids: set[int], booster_ids: set[int], author_is_local: bool,
                         mentioned_ids: list[int] | None = None) -> bool:
    mentioned_set = set(mentioned_ids) if mentioned_ids else set()
    if tl_type == "home":
        if user_id == author_id:
            return True
        if user_id in mentioned_set:
            return True
        if visibility in ("public", "home", "followers"):
            return user_id in follower_ids or user_id in booster_ids
        return False
    elif tl_type == "social":
        if user_id == author_id:
            return True
        if user_id in mentioned_set:
            return True
        if visibility == "public":
            return user_id in follower_ids or user_id == author_id or author_is_local
        if visibility in ("home", "followers"):
            return user_id in follower_ids
        return False
    elif tl_type == "local":
        return visibility == "public" and author_is_local
    else:
        return visibility == "public"
