import os
import sys
import traceback
import threading
import uvicorn

import sqlalchemy
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import CORS_ORIGINS
from app.core.activitypub import _cleanup_expired_media, _cleanup_remote_data
from app.core.push import init_vapid_keys
from app.core.workers import delivery_worker, refresh_remote_profiles, auto_delete_expired_posts
from app.db.database import get_session, init_db
from app.middleware import CSRFProtectionMiddleware, LogRequestsMiddleware
from app.routes.api import router as api_router, _cleanup_avatars
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.mastodon_api import router as mastodon_api_router
from app.routes.ap import router as ap_router
from app.routes.nodeinfo import router as nodeinfo_router
from app.routes.streaming import router as streaming_router
from app.routes.oauth import router as oauth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        with get_session() as s:
            inspector = sqlalchemy.inspect(s.bind)
            cols = [c["name"] for c in inspector.get_columns("posts")]
            if "link_preview" not in cols:
                s.execute(sqlalchemy.text("ALTER TABLE posts ADD COLUMN link_preview JSON"))
                s.commit()
            if "quote_of_id" not in cols:
                s.execute(sqlalchemy.text("ALTER TABLE posts ADD COLUMN quote_of_id INTEGER"))
                s.commit()
            if "quote_of_ap_id" not in cols:
                s.execute(sqlalchemy.text("ALTER TABLE posts ADD COLUMN quote_of_ap_id VARCHAR(1024) DEFAULT ''"))
                s.commit()
    except Exception:
        pass
    try:
        _cleanup_avatars()
    except Exception:
        pass
    try:
        with get_session() as s:
            inspector = sqlalchemy.inspect(s.bind)
            cols = [c["name"] for c in inspector.get_columns("push_subscriptions")]
            if "device_name" not in cols:
                s.execute(sqlalchemy.text("ALTER TABLE push_subscriptions ADD COLUMN device_name VARCHAR(256) DEFAULT ''"))
                s.commit()
    except Exception:
        pass
    try:
        init_vapid_keys()
    except Exception:
        pass
    t = threading.Thread(target=delivery_worker, daemon=True)
    t.start()
    t2 = threading.Thread(target=refresh_remote_profiles, daemon=True)
    t2.start()
    t3 = threading.Thread(target=auto_delete_expired_posts, daemon=True)
    t3.start()
    _cleanup_expired_media()
    _cleanup_remote_data()
    yield

app = FastAPI(title="WRIT, the sns for writers", version="1.0.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR] {request.method} {request.url.path} raised {type(exc).__name__}: {exc}", flush=True)
    print(f"[ERROR] {'='*60}", flush=True)
    traceback.print_exc()
    print(f"[ERROR] {'='*60}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get('/favicon.ico', include_in_schema=False)
def favicon():
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

_emoji_static_dir = os.path.join(os.path.dirname(__file__), "..", "web", "public", "emojis")
if os.path.isdir(_emoji_static_dir):
    app.mount("/emojis", StaticFiles(directory=_emoji_static_dir), name="emojis")

# AP/WebFinger routes must be registered before routers to take priority
app.include_router(ap_router)
app.include_router(nodeinfo_router)
app.include_router(streaming_router)
app.include_router(oauth_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(api_router)
app.include_router(mastodon_api_router, prefix="/api/v1")


# Run
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
