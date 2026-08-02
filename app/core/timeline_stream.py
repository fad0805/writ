import json
import asyncio
import logging

from sqlalchemy import func

from app.db.database import get_session
from app.models import Notification

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
