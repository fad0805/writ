import logging
import os
import threading
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config.settings import CORS_ORIGINS
from app.core.activitypub import _cleanup_expired_media, _cleanup_remote_data
from app.core.permissions import ensure_default_roles
from app.core.push import init_vapid_keys
from app.core.workers import auto_delete_expired_posts, cleanup_orphan_media, delivery_worker, refresh_remote_profiles
from app.middleware import CSRFProtectionMiddleware, LogRequestsMiddleware
from app.routes.admin import router as admin_router
from app.routes.ap import router as ap_router
from app.routes.api import router as api_router
from app.routes.mastodon_api import MastodonAPIError, oauth_router
from app.routes.mastodon_api import router as mastodon_api_router
from app.routes.nodeinfo import router as nodeinfo_router
from app.routes.streaming import router as streaming_router
from app.utils.emoji import EMOJI_DIR, _migrate_legacy_emoji_files
from app.utils.storage import _cleanup_avatars

logger = logging.getLogger("writ.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    with suppress(Exception):
        ensure_default_roles()
    with suppress(Exception):
        _cleanup_avatars()
    with suppress(Exception):
        init_vapid_keys()
    t = threading.Thread(target=delivery_worker, daemon=True)
    t.start()
    t2 = threading.Thread(target=refresh_remote_profiles, daemon=True)
    t2.start()
    t3 = threading.Thread(target=auto_delete_expired_posts, daemon=True)
    t3.start()
    t4 = threading.Thread(target=cleanup_orphan_media, daemon=True)
    t4.start()
    _cleanup_expired_media()
    _cleanup_remote_data()
    yield
    # 대기열에 남은 작업을 취소해 종료/리로드 지연을 줄인다 (실행 중 작업은 그대로 마무리)
    from app.core.activitypub import _inbox_executor
    from app.routes.api._post_create import _post_create_executor
    _post_create_executor.shutdown(wait=False, cancel_futures=True)
    _inbox_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="WRIT, the sns for writers", version="1.0.0", lifespan=lifespan)


@app.exception_handler(MastodonAPIError)
async def mastodon_api_error_handler(request: Request, exc: MastodonAPIError):
    logger.error("%s %s MastodonAPIError %s: %s", request.method, request.url.path, exc.status_code, exc.detail)
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error("%s %s HTTPException %s: %s", request.method, request.url.path, exc.status_code, exc.detail)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception):
    logger.exception("%s %s raised %s: %s", request.method, request.url.path, type(exc).__name__, exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.api_route('/favicon.ico', methods=["GET", "HEAD"], include_in_schema=False)
def favicon(request: Request):
    if request.method == "HEAD":
        return Response(headers={"Cache-Control": "no-cache", "Location": "/api/pwa/favicon"}, status_code=307)
    return RedirectResponse(url="/api/pwa/favicon", headers={"Cache-Control": "no-cache"})


app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(LogRequestsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
import app.config.settings as _settings

if not _settings.S3_ENABLED:
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

_emoji_static_dir = EMOJI_DIR
try:
    os.makedirs(_emoji_static_dir, exist_ok=True)
    _migrate_legacy_emoji_files()
except Exception:
    pass
if os.path.isdir(_emoji_static_dir):
    app.mount("/emojis", StaticFiles(directory=_emoji_static_dir), name="emojis")

# AP/WebFinger routes must be registered before routers to take priority
app.include_router(ap_router)
app.include_router(nodeinfo_router)
app.include_router(streaming_router)
app.include_router(oauth_router)
app.include_router(admin_router)
app.include_router(api_router)
app.include_router(mastodon_api_router, prefix="/api")


# Run
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
