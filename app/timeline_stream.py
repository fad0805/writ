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
        _main_loop.call_soon_threadsafe(queue.put_nowait, item)
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

def broadcast_post(post_json: dict, post_author_id: int, post_visibility: str, post_is_dm: bool):
    if post_visibility not in ("public", "home", "followers") or not _streams:
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
        follower_ids = {f.follower_id for f in s.query(Follow).filter_by(
            following_id=post_author_id, accepted=True
        ).all()}
        booster_ids = {b.user_id for b in s.query(Boost).join(Post, Boost.post_id == Post.id).filter(
            Post.author_id == post_author_id
        ).all()}
        author = s.query(User).get(post_author_id)
        author_is_local = author.is_remote == False if author else False

        # Pre-load following lists for home timeline streams
        home_uids = {info["user_id"] for info in _streams.values() if info.get("tl_type") == "home"}
        home_follows = {}
        if home_uids:
            for f in s.query(Follow).filter(Follow.follower_id.in_(home_uids), Follow.accepted == True).all():
                home_follows.setdefault(f.follower_id, set()).add(f.following_id)

        for sid, info in list(_streams.items()):
            uid = info["user_id"]
            tl = info["tl_type"]
            if not _should_deliver_fast(uid, tl, post_author_id, post_visibility, follower_ids, booster_ids, author_is_local):
                continue
            # Additional filtering for home timeline
            if tl == "home" and (mentioned_ids or parent_author_id):
                user_follows = home_follows.get(uid, set()) | {uid}
                # Filter: mention of non-followed user
                if mentioned_ids:
                    skip = False
                    for muid in mentioned_ids:
                        if muid != post_author_id and muid not in user_follows:
                            skip = True
                            break
                    if skip:
                        continue
                # Filter: parent author not followed
                if parent_author_id and parent_author_id != uid and parent_author_id not in user_follows:
                    continue
            _enqueue(info["queue"], payload)

_notif_streams: dict[int, dict] = {}
_notif_counter = 0

def add_notif_stream(user_id: int = 0) -> tuple[int, asyncio.Queue]:
    global _notif_counter
    _set_loop()
    _notif_counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _notif_streams[_notif_counter] = {"queue": q, "user_id": user_id}
    logger.info("add_notif_stream: sid=%s uid=%s total=%s", _notif_counter, user_id, len(_notif_streams))
    return _notif_counter, q

def remove_notif_stream(sid: int):
    logger.info("remove_notif_stream: sid=%s remaining=%s", sid, len(_notif_streams) - 1)
    _notif_streams.pop(sid, None)

def broadcast_notif(payload: str, target_user_id: int = 0):
    logger.info("broadcast_notif: payload=%s target=%s streams=%s", payload, target_user_id, len(_notif_streams))
    for info in list(_notif_streams.values()):
        if target_user_id == 0 or info.get("user_id") == target_user_id:
            _enqueue(info["queue"], payload)

def broadcast_refresh_notifs(target_user_id: int = 0):
    logger.info("broadcast_refresh_notifs called target=%s", target_user_id)
    broadcast_notif("refresh", target_user_id)


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
