import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.auth import _decode_session_token
from app.core.eventbus import add_queue, add_ws, remove_queue, remove_ws
from app.db.database import get_session
from app.models import MastodonAccessToken

router = APIRouter()


def _verify_session_cookie(request: Request) -> bool:
    """Verify session cookie signature/expiry (HMAC-verified)."""
    token = request.cookies.get("session")
    if not token:
        return False
    return _decode_session_token(token) is not None


@router.get("/api/stream")
async def sse_stream(request: Request):
    if not _verify_session_cookie(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    add_queue(q)
    async def event_gen() -> AsyncGenerator[str, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield payload
                except TimeoutError:
                    yield ":keepalive\n\n"
        finally:
            remove_queue(q)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.websocket("/api/v1/streaming")
async def websocket_stream(websocket: WebSocket):
    token = websocket.cookies.get("session")
    access_token = websocket.query_params.get("access_token", "")
    if not token and not access_token:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    if not token and access_token:
        with get_session() as db:
            mat = db.query(MastodonAccessToken).filter_by(access_token=access_token).first()
            if not mat or mat.user_id is None:
                await websocket.close(code=4001, reason="Unauthorized")
                return
    if token and _decode_session_token(token) is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    await websocket.accept()
    ws_id, ws_q = add_ws()
    try:
        while True:
            try:
                payload = await asyncio.wait_for(ws_q.get(), timeout=30)
                await websocket.send_text(payload)
            except TimeoutError:
                await websocket.send_text(json.dumps({"event": "ping"}))
    except Exception:
        pass
    finally:
        remove_ws(ws_id)
