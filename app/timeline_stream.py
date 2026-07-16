import json
import asyncio
import logging
import traceback
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

def broadcast_post(post_json: dict, post_author_id: int, post_visibility: str, post_is_dm: bool, mentioned_ids = None):
    try:
        if post_visibility not in ("public", "home", "followers", "mention") or not _streams:
            return

        # content가 dict 타입으로 잘못 유입되었는지 방어 코드 추가
        if isinstance(post_json.get("content"), dict):
            # dict 형태라면 특정 언어 코드를 가져오거나 문자열로 강제 치환
            content_dict = post_json["content"]
            post_json["content"] = content_dict.get("html") or content_dict.get("text") or str(content_dict)

        if not post_json.get("author"):
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
            post_id_for_boost = post_json.get("id")
            follower_ids = {f.follower_id for f in s.query(Follow).filter_by(
                following_id=post_author_id, accepted=True
            ).all()}
            booster_ids = {b.user_id for b in s.query(Boost).filter_by(post_id=post_id_for_boost).all()}
            # Also include followers of any user who boosted this post
            if booster_ids:
                for bf in s.query(Follow).filter(
                    Follow.following_id.in_(booster_ids), Follow.accepted == True
                ).all():
                    follower_ids.add(bf.follower_id)
            author = s.query(User).get(post_author_id)
            author_is_local = author.is_remote == False if author else False

            # Pre-load following lists for home/social timeline streams
            home_uids = {info["user_id"] for info in _streams.values() if info.get("tl_type") in ("home", "social")}
            home_follows = {}
            if home_uids:
                for f in s.query(Follow).filter(Follow.follower_id.in_(home_uids), Follow.accepted == True).all():
                    home_follows.setdefault(f.follower_id, set()).add(f.following_id)

            for sid, info in list(_streams.items()):
                uid = info["user_id"]
                tl = info["tl_type"]
                if not _should_deliver_fast(uid, tl, post_author_id, post_visibility, follower_ids, booster_ids, author_is_local, mentioned_ids):
                    continue
                # Additional filtering for home/social timeline (skip for mention visibility - targeted delivery)
                if tl in ("home", "social") and post_visibility != "mention":
                    user_follows = home_follows.get(uid, set()) | {uid}
                    content = post_json.get("content") or ""
                    # [1] 멘션 필터링 (DB ID 기반 + 리모트 HTML 본문 정규식 검사)
                    skip_mention = False
                    # 1-A. 페이로드에 명시된 멘션 ID 목록 검사
                    if mentioned_ids:
                        if uid in mentioned_ids:
                            _enqueue(info["queue"], payload)
                            continue
                        for muid in mentioned_ids:
                            if muid != post_author_id and muid not in user_follows and muid != uid:
                                skip_mention = True
                                break
                    # 1-B. 리모트 글인 경우, 본문 HTML 태그에서 내가 팔로우하지 않는 제3자에게 쏘는 멘션 링크 검사
                    if not skip_mention and content and author_is_local is False:
                        import re as _re
                        mentions_in_html = _re.findall(r'<a\s+[^>]*href="([^"]+)"[^>]*class="[^"]*mention[^"]*"[^>]*>', content)
                        if mentions_in_html:
                            # 본문 멘션 중 나를 향한 것이 있으면 스킵하지 않음
                            my_username = author.username.split("@")[0] if author else ""
                            is_mentioned_in_html = any(
                                f"/@{my_username}" in m or f"/@{uid}" in m
                                for m in mentions_in_html
                            )
                            if not is_mentioned_in_html:
                                skip_mention = True
                    if skip_mention:
                        print(f"Stream filter: dropped post {post_json.get('id')} from uid={uid} (mention not followed)", flush=True)
                        continue

                    # [2] 답글(Reply) 필터링 (부모 글 작성자 미팔로우 방어)
                    if post_json.get("boosted_by"):
                        pass
                    elif bool(post_json.get("in_reply_to_id") or post_json.get("in_reply_to_ap_id") or reply_ctx):
                        if parent_author_id is None:
                            print(f"Stream filter: dropped reply {post_json.get('id')} (parent author unverified)", flush=True)
                            continue
                        if parent_author_id != uid and parent_author_id not in user_follows and uid != post_author_id:
                            print(f"Stream filter: dropped reply {post_json.get('id')} (parent author {parent_author_id} not followed)", flush=True)
                            continue
                _enqueue(info["queue"], payload)
    except Exception as e:
        print("!!! BROADCAST_POST ERROR !!!", flush=True)
        traceback.print_exc()

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
    if target_user_id != 0:
        broadcast_notif(json.dumps({"event": "notif"}), target_user_id)

def broadcast_notif_sound(target_user_id: int):
    """Send a JSON event that triggers notification sound in the browser."""
    broadcast_notif(json.dumps({"event": "notif"}), target_user_id)


def broadcast_delete(post_id: int):
    """Broadcast a delete event to all connected timeline streams."""
    if not _streams:
        return
    payload = json.dumps({"type": "delete", "id": post_id})
    for info in list(_streams.values()):
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
            return True
        if visibility in ("home", "followers"):
            return user_id in follower_ids
        return False
    elif tl_type == "local":
        return visibility == "public" and author_is_local
    else:
        return visibility == "public"
