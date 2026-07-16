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
        if post_visibility not in ("public", "home", "followers") or not _streams:
            return

        # content가 dict 타입으로 잘못 유입되었는지 방어 코드 추가
        if isinstance(post_json.get("content"), dict):
            # dict 형태라면 특정 언어 코드를 가져오거나 문자열로 강제 치환
            content_dict = post_json["content"]
            post_json["content"] = content_dict.get("html") or content_dict.get("text") or str(content_dict)

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
                if not _should_deliver_fast(uid, tl, post_author_id, post_visibility, follower_ids, booster_ids, author_is_local):
                    continue
                # Additional filtering for home/social timeline
                if tl in ("home", "social"):
                    user_follows = home_follows.get(uid, set()) | {uid}
                    content = post_json.get("content") or ""
                    # [1] 멘션 필터링 (DB ID 기반 + 리모트 HTML 본문 정규식 검사)
                    skip_mention = False
                    # 1-A. 페이로드에 명시된 멘션 ID 목록 검사
                    if mentioned_ids:
                        for muid in mentioned_ids:
                            if muid != post_author_id and muid not in user_follows:
                                skip_mention = True
                                break
                    # 1-B. 리모트 글인 경우, 본문 HTML 태그에서 내가 팔로우하지 않는 제3자에게 쏘는 멘션 링크 검사
                    # (리모트 글은 언급 ID가 비어있는 채로 오기 때문에 HTML 본문을 직접 뜯어야 합니다)
                    if not skip_mention and content and author_is_local is False:
                        import re as _re
                        # href 내부에 클래스명이 mention인 앵커 태그들의 URL 추출
                        mentions_in_html = _re.findall(r'<a\s+[^>]*href="([^"]+)"[^>]*class="[^"]*mention[^"]*"[^>]*>', content)
                        if mentions_in_html:
                            # 내가 안 흔든 사람(제3자)으로 향하는 멘션 링크가 본문에 보이면 우선 필터링
                            # (스트리밍 세션 성능을 위해 무거운 DB 조회 없이 멘션의 존재 여부로 빠르게 skip 처리합니다)
                            skip_mention = True
                    if skip_mention:
                        logger.info("Stream filter: dropped post %s from uid=%s (mention not followed)", post_json.get("id"), uid)
                        continue

                    # [2] 답글(Reply) 필터링 (부모 글 작성자 미팔로우 방어)
                    # 부스트인 경우 스킵 (boosted_by가 있으면 부스트)
                    if post_json.get("boosted_by"):
                        pass
                    elif bool(post_json.get("in_reply_to_id") or post_json.get("in_reply_to_ap_id") or reply_ctx):
                        # 부모 작성자가 아예 누군지 파악이 안 되거나, 
                        # 파악이 되었더라도 내가 팔로우하는 사람이 아니며, 내가 쓴 답글도 아니라면 홈 피드 전송 차단!
                        if parent_author_id is None:
                            # 부모 작성자 정보가 아예 누락된 리모트 답글은 안전하게 차단
                            logger.info("Stream filter: dropped reply %s (parent author unverified)", post_json.get("id"))
                            continue
                        # 부모 작성자가 존재할 때, 검증 로직
                        if parent_author_id != uid and parent_author_id not in user_follows and uid != post_author_id:
                            logger.info("Stream filter: dropped reply %s (parent author %s not followed)", post_json.get("id"), parent_author_id)
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
