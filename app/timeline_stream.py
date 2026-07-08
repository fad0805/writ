import json
import asyncio
import logging
from app.models import get_session, Post, Follow, User, Boost

logger = logging.getLogger(__name__)

_streams: dict[int, dict] = {}
_counter = 0

def add_stream(user_id: int, tl_type: str) -> tuple[int, asyncio.Queue]:
    global _counter
    _counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _streams[_counter] = {"queue": q, "user_id": user_id, "tl_type": tl_type}
    return _counter, q

def remove_stream(sid: int):
    _streams.pop(sid, None)

def broadcast_post(post_json: dict, post_author_id: int, post_visibility: str, post_is_dm: bool):
    if post_visibility not in ("public", "home", "followers"):
        return
    payload = json.dumps(post_json, default=str)
    with get_session() as s:
        for sid, info in list(_streams.items()):
            uid = info["user_id"]
            tl = info["tl_type"]
            if _should_deliver(s, uid, tl, post_author_id, post_visibility):
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.call_soon_threadsafe(info["queue"].put_nowait, payload)
                    else:
                        info["queue"].put_nowait(payload)
                except Exception:
                    pass

_notif_streams: dict[int, asyncio.Queue] = {}
_notif_counter = 0

def add_notif_stream() -> tuple[int, asyncio.Queue]:
    global _notif_counter
    _notif_counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _notif_streams[_notif_counter] = q
    return _notif_counter, q

def remove_notif_stream(sid: int):
    _notif_streams.pop(sid, None)

def broadcast_notif(payload: str):
    for q in list(_notif_streams.values()):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(q.put_nowait, payload)
            else:
                q.put_nowait(payload)
        except Exception:
            pass

def broadcast_refresh_notifs():
    broadcast_notif("refresh")


def _should_deliver(session, user_id: int, tl_type: str, author_id: int, visibility: str) -> bool:
    if tl_type == "home":
        if user_id == author_id:
            return True
        if visibility in ("public", "home", "followers"):
            following = session.query(Follow).filter_by(
                follower_id=user_id, following_id=author_id, accepted=True
            ).first()
            if following:
                return True
            if session.query(Boost).join(Post, Boost.post_id == Post.id).filter(
                Boost.user_id == user_id, Post.author_id == author_id
            ).first():
                return True
        return False
    elif tl_type == "social":
        if user_id == author_id:
            return True
        if visibility == "public":
            return True
        if visibility in ("home", "followers"):
            following = session.query(Follow).filter_by(
                follower_id=user_id, following_id=author_id, accepted=True
            ).first()
            return following is not None
        return False
    elif tl_type == "local":
        author = session.query(User).get(author_id)
        return visibility == "public" and author and not author.is_remote
    else:
        return visibility == "public"
