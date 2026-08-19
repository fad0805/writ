import asyncio
import contextlib
import json
import logging

from sqlalchemy import func

from app.db.database import get_session
from app.models import Notification, Post

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
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(item)
        _main_loop.call_soon_threadsafe(_put)
    else:
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(item)


def add_stream(user_id: int, tl_type: str) -> tuple[int, asyncio.Queue]:
    global _counter
    _set_loop()
    _counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _streams[_counter] = {"queue": q, "user_id": user_id, "tl_type": tl_type}
    return _counter, q


def remove_stream(sid: int):
    _streams.pop(sid, None)


_notif_streams: dict[int, dict] = {}
_notif_counter = 0

def add_notif_stream(user_id: int = 0) -> tuple[int, asyncio.Queue]:
    global _notif_counter
    _set_loop()
    _notif_counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _notif_streams[_notif_counter] = {"queue": q, "user_id": user_id}
    logger.debug("[SSE] add_notif_stream: sid=%s uid=%s total=%s", _notif_counter, user_id, len(_notif_streams))
    return _notif_counter, q

def remove_notif_stream(sid: int):
    logger.debug("[SSE] remove_notif_stream: sid=%s remaining=%s", sid, len(_notif_streams) - 1)
    _notif_streams.pop(sid, None)

def broadcast_notif(payload: str, target_user_id: int = 0):
    logger.debug("[SSE] broadcast_notif: target=%s streams=%s", target_user_id, len(_notif_streams))
    for info in list(_notif_streams.values()):
        if target_user_id == 0 or info.get("user_id") == target_user_id:
            _enqueue(info["queue"], payload)

def broadcast_refresh_notifs(target_user_id: int = 0):
    logger.debug("[SSE] broadcast_refresh_notifs target=%s", target_user_id)
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


def broadcast_profile_update(user_id: int):
    """Broadcast a profile update event to all connected timeline streams."""
    payload = json.dumps({"type": "profile_update", "user_id": user_id})
    for info in list(_streams.values()):
        _enqueue(info["queue"], payload)


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


def _post_visibility_author(post_id: int) -> tuple[bool, int | None]:
    """(공개 여부, 작성자 id). 삭제된 글/오류 시 (True, None)로 안전하게 전역 브로드캐스트."""
    try:
        with get_session() as s:
            p = s.query(Post).filter_by(id=post_id).first()
            if p is None:
                return True, None
            return p.visibility in ("public", "unlisted", "home"), p.author_id
    except Exception:
        return True, None


def broadcast_reaction_update(post_id: int, reactions: dict):
    """Broadcast updated reactions dict for a post to all connected timeline streams and post streams."""
    likes_count = sum(v for v in reactions.values() if isinstance(v, (int, float)))
    payload = json.dumps({"type": "update", "id": post_id, "reactions": reactions, "likes_count": likes_count}, default=str)
    # 비공개/DM/팔로워 전용 글은 작성자에게만 푸시해 다른 사용자의 타임라인
    # 스트림으로 존재·리액션 정보가 새어나가는 것을 막는다. (글 스트림은
    # 구독 시 _can_view로 이미 검증된 구독자에게만 전달된다.)
    is_public, author_id = _post_visibility_author(post_id)
    for info in list(_streams.values()):
        if is_public or info.get("user_id") == author_id:
            _enqueue(info["queue"], payload)
    for info in list(_post_streams.values()):
        if info["post_id"] == post_id:
            _enqueue(info["queue"], payload)
    # Boost pointer posts show the original's reactions, so broadcast to them too.
    try:
        with get_session() as s:
            bp_ids = [row[0] for row in s.query(Post.id).filter(
                Post.boost_of_id == post_id, Post.is_deleted == False).all()]
    except Exception:
        bp_ids = []
    for bp_id in bp_ids:
        bp_payload = json.dumps({"type": "update", "id": bp_id, "reactions": reactions, "likes_count": likes_count}, default=str)
        for info in list(_streams.values()):
            if is_public or info.get("user_id") == author_id:
                _enqueue(info["queue"], bp_payload)
        for info in list(_post_streams.values()):
            if info["post_id"] == bp_id:
                _enqueue(info["queue"], bp_payload)
