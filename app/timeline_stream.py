import json
import asyncio
import logging
from app.models import get_session, Post, Follow, User, Boost

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
        print(f"[TIMING] _enqueue call_soon_threadsafe (queue={queue})")
        _main_loop.call_soon_threadsafe(queue.put_nowait, item)
    else:
        print(f"[TIMING] _enqueue fallback (loop={_main_loop}, running={_main_loop.is_running() if _main_loop else 'N/A'})")
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

def broadcast_post(post_json: dict, post_author_id: int, post_visibility: str, post_is_dm: bool):
    import time as _time
    _t0 = _time.time()
    if post_visibility not in ("public", "home", "followers") or not _streams:
        return
    _t1 = _time.time()
    payload = json.dumps(post_json, default=str)
    print(f"[TIMING] broadcast_post json.dumps: {_time.time()-_t1:.3f}s")
    with get_session() as s:
        _t2 = _time.time()
        follower_ids = {f.follower_id for f in s.query(Follow).filter_by(
            following_id=post_author_id, accepted=True
        ).all()}
        print(f"[TIMING] broadcast_post query followers: {_time.time()-_t2:.3f}s ({len(follower_ids)} found)")
        _t3 = _time.time()
        booster_ids = {b.user_id for b in s.query(Boost).join(Post, Boost.post_id == Post.id).filter(
            Post.author_id == post_author_id
        ).all()}
        print(f"[TIMING] broadcast_post query boosters: {_time.time()-_t3:.3f}s ({len(booster_ids)} found)")
        _t4 = _time.time()
        author = s.query(User).get(post_author_id)
        author_is_local = author.is_remote == False if author else False
        print(f"[TIMING] broadcast_post query author: {_time.time()-_t4:.3f}s")

        delivered = 0
        for sid, info in list(_streams.items()):
            uid = info["user_id"]
            tl = info["tl_type"]
            if _should_deliver_fast(uid, tl, post_author_id, post_visibility, follower_ids, booster_ids, author_is_local):
                _enqueue(info["queue"], payload)
                delivered += 1
        print(f"[TIMING] broadcast_post TOTAL: {_time.time()-_t0:.3f}s ({delivered} streams, {len(_streams)} total)")

_notif_streams: dict[int, asyncio.Queue] = {}
_notif_counter = 0

def add_notif_stream() -> tuple[int, asyncio.Queue]:
    global _notif_counter
    _set_loop()
    _notif_counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _notif_streams[_notif_counter] = q
    return _notif_counter, q

def remove_notif_stream(sid: int):
    _notif_streams.pop(sid, None)

def broadcast_notif(payload: str):
    for q in list(_notif_streams.values()):
        _enqueue(q, payload)

def broadcast_refresh_notifs():
    broadcast_notif("refresh")


def _should_deliver_fast(user_id: int, tl_type: str, author_id: int, visibility: str,
                         follower_ids: set[int], booster_ids: set[int], author_is_local: bool) -> bool:
    if tl_type == "home":
        if user_id == author_id:
            return True
        if visibility in ("public", "home", "followers"):
            return user_id in follower_ids or user_id in booster_ids
        return False
    elif tl_type == "social":
        if user_id == author_id:
            return True
        if visibility == "public":
            return True
        if visibility in ("home", "followers"):
            return user_id in follower_ids
        return False
    elif tl_type == "local":
        return visibility == "public" and author_is_local
    else:
        return visibility == "public"
