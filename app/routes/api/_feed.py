"""Timeline/feed endpoints extracted from _posts.py."""
import asyncio
import datetime
import logging

from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.feed import _get_feed
from app.core.timeline_stream import add_post_stream, remove_post_stream
from app.db.database import get_db
from app.core.auth import get_current_user

logger = logging.getLogger("writ.api.feed")

feed_router = APIRouter()

TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


def _parse_cursor(cursor: str | None):
    """'<created_at_iso>|<id>' 커서를 (datetime, id)로 복원한다. 파싱 실패 시 None."""
    if not cursor:
        return None
    try:
        ts, _, pid = cursor.rpartition("|")
        return datetime.datetime.fromisoformat(ts), int(pid)
    except (ValueError, TypeError):
        return None


@feed_router.get("/posts/{post_id}/stream")
async def api_post_stream(request: Request, post_id: int):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    sid, q = add_post_stream(post_id)
    async def event_gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
        finally:
            remove_post_stream(sid)
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@feed_router.get("/timeline/{tl_type}")
def api_timeline(request: Request, tl_type: str, limit: int = Query(10), offset: int = Query(0), cursor: str | None = Query(None), s: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if getattr(user, 'is_deactivated', False):
        return JSONResponse({"error": "Account deactivated"}, status_code=403)
    if tl_type not in TIMELINE_LABELS:
        tl_type = "home"
    feed, has_more, emojis, next_cursor = _get_feed(user, tl_type, s, limit=limit, offset=offset, cursor=_parse_cursor(cursor))
    return {"posts": feed, "timeline_type": tl_type, "has_more": has_more, "cursor": next_cursor, "_emojis": emojis}
