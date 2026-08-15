import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError

from app.core.activitypub._inbound_create import _handle_create
from app.core.activitypub._inbound_follow import _handle_accept, _handle_follow, _handle_reject
from app.core.activitypub._inbound_interactions import (
    _handle_announce,
    _handle_block,
    _handle_delete,
    _handle_flag,
    _handle_like,
    _handle_move,
    _handle_undo,
    _handle_update,
    _handle_vote,
)
from app.core.federation import federation_allowed
from app.db.database import get_session
from app.models import ProcessedActivity

logger = logging.getLogger("writ.activitypub")

# 리모트 inbox 처리용 전용 executor. 글/답글 작성과는 분리된 풀을 쓰고
# 동시 처리 수를 제한해, 한쪽의 네트워크 부하가 다른 쪽을 막지 않게 한다.
# 코어 수에 맞춰 워커를 제한해 GIL 경합/커넥션 소진을 막는다.
_inbox_executor = ThreadPoolExecutor(
    max_workers=max(4, min(8, (os.cpu_count() or 1) + 1)),
    thread_name_prefix="ap-inbox",
)


def _is_activity_processed(activity_id: str) -> bool:
    """Return True if the activity was already processed (deduplication)."""
    if not activity_id:
        return False
    with get_session() as s:
        return s.query(ProcessedActivity).filter_by(id=activity_id).first() is not None


def _mark_activity_processed(activity_id: str):
    """Record an activity as processed. No-op for empty ids."""
    if not activity_id:
        return
    try:
        with get_session() as s:
            s.add(ProcessedActivity(id=activity_id))
            s.commit()
    except IntegrityError:
        # 동시 처리(TOCTOU) 시 PK 중복은 정상 — 이미 처리됨으로 간주
        pass


async def _submit_inbox(activity: dict) -> tuple[int, str]:
    """Run inbox processing on the dedicated executor pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_inbox_executor, handle_inbox, activity)


def handle_inbox(activity: dict) -> tuple[int, str]:
    atype = activity.get("type")
    actor = activity.get("actor")

    if isinstance(actor, list):
        actor = actor[0]

    actor_domain = urlparse(actor).hostname or "" if actor and isinstance(actor, str) else ""
    logger.debug("[INBOX] atype=%s actor_domain=%s", atype, actor_domain)

    # Check federation rules for the actor's domain
    if actor and isinstance(actor, str):
        actor_domain = urlparse(actor).hostname or ""
        if not federation_allowed(actor_domain):
            logger.info("Rejected inbox activity from blocked domain: %s", actor_domain)
            return (403, "Domain not allowed")

    if atype == "Follow":
        return _handle_follow(activity)
    if atype == "Accept":
        return _handle_accept(activity)
    if atype == "Reject":
        return _handle_reject(activity)
    if atype == "Create":
        return _handle_create(activity)
    if atype == "Like":
        return _handle_like(activity)
    if atype == "Announce":
        return _handle_announce(activity)
    if atype == "Undo":
        return _handle_undo(activity)
    if atype == "Update":
        return _handle_update(activity)
    if atype == "Delete":
        return _handle_delete(activity)
    if atype == "Flag":
        return _handle_flag(activity)
    if atype == "Move":
        return _handle_move(activity)
    if atype == "Vote":
        return _handle_vote(activity)
    if atype == "EmojiReact":
        return _handle_like(activity)
    if atype == "Block":
        return _handle_block(activity)
    return (202, f"Accepted {atype}")


# Re-export names consumed by app.core.activitypub.__init__
from app.core.activitypub._inbound_common import (  # noqa: F401
    _broadcast_emoji_list,
    _build_reactions,
    _sanitize_reaction,
)
