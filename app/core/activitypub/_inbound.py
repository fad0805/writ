import asyncio
import datetime as dt
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


# 처리 중 상태가 이보다 오래되면 이전 워커가 죽은 것으로 보고 재처리한다.
_PROCESSING_TTL = dt.timedelta(minutes=15)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _claim_activity(activity_id: str) -> dt.datetime | None:
    """활동 처리를 원자적으로 예약한다. 예약하면 소유 토큰을 반환한다.

    새 행을 'processing' 상태로 INSERT 해서 동시 요청 중 하나만 처리한다.
    기존 행이 'done'이면 중복 요청, 'processing'이면 아직 처리 중이거나
    이전 워커가 죽은 경우다. TTL이 지난 processing 행만 원자적으로 재예약한다.
    """
    if not activity_id:
        return _utcnow()
    token = _utcnow()
    try:
        with get_session() as s:
            s.add(ProcessedActivity(id=activity_id, status="processing", created_at=token))
            s.commit()
            return token
    except IntegrityError:
        pass

    cutoff = _utcnow() - _PROCESSING_TTL
    with get_session() as s:
        row = s.query(ProcessedActivity).filter_by(id=activity_id).first()
        if row is None or row.status == "done" or row.created_at is None:
            return None
        created = row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.UTC)
        if created > cutoff:
            return None
        new_token = _utcnow()
        updated = (
            s.query(ProcessedActivity)
            .filter(
                ProcessedActivity.id == activity_id,
                ProcessedActivity.status == "processing",
                ProcessedActivity.created_at <= cutoff,
            )
            .update(
                {"created_at": new_token, "status": "processing"},
                synchronize_session=False,
            )
        )
        s.commit()
        return new_token if updated == 1 else None


def _finish_activity(activity_id: str, token: dt.datetime | None, success: bool):
    """예약한 활동을 완료 처리하거나, 실패 시 예약을 취소해 재전송을 허용한다."""
    if not activity_id or token is None:
        return
    with get_session() as s:
        query = s.query(ProcessedActivity).filter(
            ProcessedActivity.id == activity_id,
            ProcessedActivity.status == "processing",
            ProcessedActivity.created_at == token,
        )
        if success:
            query.update({"status": "done"}, synchronize_session=False)
        else:
            query.delete(synchronize_session=False)
        s.commit()


def _is_activity_processed(activity_id: str) -> bool:
    """기존 호출부용: 완료된 활동만 중복으로 간주한다."""
    if not activity_id:
        return False
    with get_session() as s:
        row = s.query(ProcessedActivity).filter_by(id=activity_id).first()
        return row is not None and row.status == "done"


def _mark_activity_processed(activity_id: str):
    """기존 호출부용: 활동을 완료 상태로 기록한다."""
    if not activity_id:
        return
    try:
        with get_session() as s:
            s.add(ProcessedActivity(id=activity_id, status="done"))
            s.commit()
    except IntegrityError:
        with get_session() as s:
            s.query(ProcessedActivity).filter_by(id=activity_id).update(
                {"status": "done"}, synchronize_session=False
            )
            s.commit()


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
