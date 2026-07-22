import base64
import datetime
import email.utils
import hashlib
import hmac as _hmac
import json
import os
import logging
import secrets
import threading
import time
from collections import defaultdict
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from urllib.parse import urlparse
from app.crypto_utils import verify_signature
from app.config import SECRET_KEY, BASE_URL, DOMAIN, CORS_ORIGINS
from app.logging_config import _request_logger
from app.models import User, Follow, Post, Novel, ProcessedActivity, get_session, init_db
from app.routes.auth import router as auth_router
from app.routes.api import router as api_router
from app.routes.admin import router as admin_router
from app.activitypub import (
    get_outbox, get_followers, get_following, handle_inbox,
    _deliver_sync, _cleanup_expired_media, _cleanup_remote_data,
    _resolve_actor,
)

_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_RATE_LIMIT_BURST = 10
_RATE_LIMIT_DAILY = 500
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_daily: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()

_actor_fail_cache: dict[str, float] = {}  # actor_url -> timestamp of last failure
_ACTOR_FAIL_TTL = 3600  # 1 hour


def _check_rate_limit(key: str) -> bool:
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    with _rate_limit_lock:
        timestamps = _rate_limit_store[key]
        pruned = [t for t in timestamps if t > window_start]
        if len(pruned) >= _RATE_LIMIT_MAX:
            return False
        _rate_limit_store[key] = pruned + [now]
        return True


def _check_burst_limit(key: str) -> bool:
    now = time.time()
    burst_start = now - 5
    with _rate_limit_lock:
        timestamps = _rate_limit_store[key]
        recent = [t for t in timestamps if t > burst_start]
        if len(recent) >= _RATE_LIMIT_BURST:
            return False
        return True


def _check_daily_limit(key: str) -> bool:
    now = time.time()
    day_start = now - 86400
    with _rate_limit_lock:
        timestamps = _rate_limit_daily[key]
        pruned = [t for t in timestamps if t > day_start]
        if len(pruned) >= _RATE_LIMIT_DAILY:
            return False
        _rate_limit_daily[key] = pruned + [now]
        return True

def _delivery_worker():
    from app.models import PendingDelivery, get_session
    from app.crypto_utils import sign_string, get_private_key
    while True:
        time.sleep(30)
        try:
            with get_session() as s:
                items = s.query(PendingDelivery).filter_by(status="pending").order_by(PendingDelivery.created_at).limit(50).all()
                for item in items:
                    try:
                        sender = s.query(User).get(item.sender_id)
                        if not sender:
                            item.status = "failed"
                            item.last_error = "Sender not found"
                            continue
                        activity = json.loads(item.activity_json)
                        body = json.dumps(activity, ensure_ascii=True, sort_keys=True).encode("utf-8")
                        digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
                        date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                        parsed = urlparse(item.inbox_url)
                        path = parsed.path or "/"
                        signed_string = f"(request-target): post {path}\nhost: {parsed.netloc}\ndate: {date}\ndigest: SHA-256={digest}"
                        signature = sign_string(signed_string, get_private_key(sender, SECRET_KEY))
                        signature_header = (
                            f'keyId="{sender.actor_uri()}#main-key",'
                            f'algorithm="rsa-sha256",'
                            f'headers="(request-target) host date digest",'
                            f'signature="{signature}"'
                        )
                        headers = {
                            "Content-Type": "application/activity+json",
                            "Signature": signature_header,
                            "Date": date,
                            "Digest": f"SHA-256={digest}",
                            "Host": parsed.netloc,
                        }
                        ok = _deliver_sync(item.inbox_url, body, headers)
                        if ok:
                            s.delete(item)
                        else:
                            item.attempts += 1
                            if item.attempts >= 7:
                                item.status = "failed"
                            item.last_error = "Max retries reached"
                    except Exception as e:
                        item.attempts += 1
                        item.last_error = str(e)
                        if item.attempts >= 7:
                            item.status = "failed"
                s.commit()
        except Exception as e:
            logger.error("Delivery worker error: %s", e)


def _refresh_remote_profiles():
    """Cycle updated_at so oldest-refreshed users get picked eventually (HTTP refresh is manual)."""
    while True:
        time.sleep(600)
        try:
            from app.models import User, get_session
            with get_session() as _s:
                for ru in _s.query(User).filter(User.is_remote == True).order_by(User.updated_at.asc()).limit(5).all():
                    ru.updated_at = datetime.datetime.now(datetime.timezone.utc)
                _s.commit()
        except Exception:
            pass


def _auto_delete_expired_posts():
    """Hard-delete expired posts daily at 3 AM server time.
    Checks CPU and DB load before and during execution; aborts if too busy.
    Uses user.post_lifetime (days) + post.created_at to determine expiry."""
    import time as _time
    import datetime as _dt

    def _next_3am():
        now = _dt.datetime.now()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= now:
            target += _dt.timedelta(days=1)
        return (target - now).total_seconds()

    def _get_cpu_percent():
        try:
            with open("/proc/stat") as f:
                parts = f.readline().split()
            idle1 = int(parts[4])
            total1 = sum(int(x) for x in parts[1:])
            import time as _time
            _time.sleep(1)
            with open("/proc/stat") as f:
                parts = f.readline().split()
            idle2 = int(parts[4])
            total2 = sum(int(x) for x in parts[1:])
            idle_d = idle2 - idle1
            total_d = total2 - total1
            if total_d == 0:
                return 0
            return (1 - idle_d / total_d) * 100
        except Exception:
            return 0

    def _server_busy():
        if _get_cpu_percent() > 70:
            return True
        try:
            from app.models import engine
            pool = engine.pool
            checkedout = pool.checkedout()
            size = pool.size()
            if size > 0 and checkedout / size > 0.8:
                return True
        except Exception:
            pass
        return False

    _time.sleep(min(_next_3am(), 300))
    while True:
        try:
            if _server_busy():
                logger.info("Auto-delete: server busy, skipping")
                _time.sleep(1800)
                continue

            from app.models import get_session, Post, User, Like, Boost, Bookmark, Vote, Notification
            with get_session() as s:
                now = _dt.datetime.now(_dt.timezone.utc)
                users_with_lifetime = s.query(User).filter(
                    User.post_lifetime > 0,
                    User.is_remote == False,
                ).all()
                deleted = 0
                for u in users_with_lifetime:
                    exc = u.post_lifetime_exceptions or []
                    cutoff = now - _dt.timedelta(days=u.post_lifetime)
                    expired = s.query(Post).filter(
                        Post.author_id == u.id,
                        Post.is_deleted == False,
                        Post.created_at <= cutoff,
                    ).all()
                    for post in expired:
                        if _server_busy():
                            logger.info("Auto-delete: server busy mid-run, stopping at %d", deleted)
                            break
                        try:
                            if "pinned" in exc and post.is_pinned:
                                continue
                            if "dm" in exc and post.is_dm:
                                continue
                            if "liked" in exc:
                                if s.query(Like).filter_by(user_id=u.id, post_id=post.id).first():
                                    continue
                            if "bookmarked" in exc:
                                if s.query(Bookmark).filter_by(user_id=u.id, post_id=post.id).first():
                                    continue
                            if "poll" in exc and post.poll_data:
                                continue
                            if "media" in exc and post.media_attachments:
                                continue
                            s.query(Notification).filter(Notification.post_id == post.id).delete()
                            s.query(Like).filter(Like.post_id == post.id).delete()
                            s.query(Boost).filter(Boost.post_id == post.id).delete()
                            s.query(Bookmark).filter(Bookmark.post_id == post.id).delete()
                            s.query(Vote).filter(Vote.post_id == post.id).delete()

                            media = list(post.media_attachments or [])
                            if media:
                                try:
                                    from app.utils.storage import get_storage
                                    storage = get_storage()
                                    for m in media:
                                        if isinstance(m, dict) and m.get("url"):
                                            try:
                                                storage.delete(m["url"])
                                            except Exception:
                                                pass
                                except Exception:
                                    pass

                            ap_id = post.ap_id or ""
                            if ap_id and ap_id.startswith("http"):
                                try:
                                    from app.activitypub import _send_delete_post
                                    _send_delete_post(post, u)
                                except Exception:
                                    pass

                            s.delete(post)
                            s.flush()

                            try:
                                from app.timeline_stream import broadcast_delete
                                broadcast_delete(post.id)
                            except Exception:
                                pass
                            deleted += 1
                        except Exception:
                            pass
                    if _server_busy():
                        break
                if deleted:
                    s.commit()
                    logger.info("Auto-deleted %d expired posts", deleted)
        except Exception as e:
            logger.error("Auto-delete worker error: %s", e)
        _time.sleep(_next_3am() + 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.routes.api import _cleanup_avatars
    init_db()
    try:
        from app.models import get_session, Post
        import sqlalchemy as _sa
        with get_session() as s:
            inspector = _sa.inspect(s.bind)
            cols = [c["name"] for c in inspector.get_columns("posts")]
            if "link_preview" not in cols:
                s.execute(_sa.text("ALTER TABLE posts ADD COLUMN link_preview JSON"))
                s.commit()
            if "quote_of_id" not in cols:
                s.execute(_sa.text("ALTER TABLE posts ADD COLUMN quote_of_id INTEGER"))
                s.commit()
            if "quote_of_ap_id" not in cols:
                s.execute(_sa.text("ALTER TABLE posts ADD COLUMN quote_of_ap_id VARCHAR(1024) DEFAULT ''"))
                s.commit()
    except Exception:
        pass
    try:
        _cleanup_avatars()
    except Exception:
        pass
    try:
        from app.models import get_session, PushSubscription
        import sqlalchemy as _sa
        with get_session() as s:
            inspector = _sa.inspect(s.bind)
            cols = [c["name"] for c in inspector.get_columns("push_subscriptions")]
            if "device_name" not in cols:
                s.execute(_sa.text("ALTER TABLE push_subscriptions ADD COLUMN device_name VARCHAR(256) DEFAULT ''"))
                s.commit()
    except Exception:
        pass
    # Initialize VAPID keys (DB-first, then auto-generate)
    try:
        from app.config import init_vapid_keys
        init_vapid_keys()
    except Exception:
        pass
    t = threading.Thread(target=_delivery_worker, daemon=True)
    t.start()
    t2 = threading.Thread(target=_refresh_remote_profiles, daemon=True)
    t2.start()
    t3 = threading.Thread(target=_auto_delete_expired_posts, daemon=True)
    t3.start()
    _cleanup_expired_media()
    _cleanup_remote_data()
    yield

app = FastAPI(title="WRIT, the sns for writers", version="1.0.0", lifespan=lifespan)

@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception):
    import traceback
    import sys
    print(f"[ERROR] {request.method} {request.url.path} raised {type(exc).__name__}: {exc}", flush=True)
    print(f"[ERROR] {'='*60}", flush=True)
    traceback.print_exc()
    print(f"[ERROR] {'='*60}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)

CSRF_EXEMPT_PREFIXES = ("/.well-known/", "/nodeinfo", "/webfinger", "/static/", "/uploads/", "/api/auth/", "/api/push/", "/inbox", "/outbox")
CSRF_EXEMPT_EXACT = ("/users/", "/posts/", "/activities/", "/@/")
CSRF_EXEMPT_METHODS = ("GET", "HEAD", "OPTIONS")


def generate_csrf_token(user_id: int) -> str:
    expires = int(time.time()) + 3600
    payload = f"{user_id}:{expires}"
    sig = _hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def validate_csrf_token(token: str, session_token: str) -> bool:
    if not token or not session_token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        user_id = int(parts[0])
        expires = int(parts[1])
        sig = parts[2]
        expected = _hmac.new(SECRET_KEY.encode(), f"{user_id}:{expires}".encode(),
                             hashlib.sha256).hexdigest()[:16]
        if not _hmac.compare_digest(sig, expected) or expires <= time.time():
            return False
        # Verify session cookie is also valid HMAC-signed (same browser)
        session_decoded = base64.urlsafe_b64decode(session_token.encode()).decode()
        session_parts = session_decoded.split(":")
        session_payload = f"{session_parts[0]}:{session_parts[1]}"
        session_sig = session_parts[2]
        session_expected = _hmac.new(SECRET_KEY.encode(), session_payload.encode(),
                                     hashlib.sha256).hexdigest()[:16]
        return _hmac.compare_digest(session_sig, session_expected)
    except Exception:
        return False


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if request.method in CSRF_EXEMPT_METHODS:
        return await call_next(request)
    path = request.url.path
    for prefix in CSRF_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return await call_next(request)
    if path in CSRF_EXEMPT_EXACT or any(path.startswith(p) for p in CSRF_EXEMPT_EXACT):
        return await call_next(request)
    session_token = request.cookies.get("session", "")
    csrf_token = request.headers.get("X-CSRF-Token", "")
    import os
    is_dev = os.getenv("APP_ENV", "production") == "development"
    if is_dev:
        pass
    else:
        host_header = request.headers.get("Host", "")
        if host_header in ("api:8000", "localhost:8000") or host_header.startswith("172."):
            host_header = DOMAIN
        origin = request.headers.get("Origin", "")
        referer = request.headers.get("Referer", "")
        if origin:
            from urllib.parse import urlparse as _urlparse
            try:
                origin_host = _urlparse(origin).netloc
            except Exception:
                origin_host = ""
            if origin_host and origin_host != host_header:
                print(f"[CSRF] origin mismatch: origin={origin_host} host={host_header}", flush=True)
                return JSONResponse({"detail": "CSRF origin mismatch"}, status_code=403)
        elif referer:
            from urllib.parse import urlparse as _urlparse
            try:
                referer_host = _urlparse(referer).netloc
            except Exception:
                referer_host = ""
            if referer_host and referer_host != host_header:
                print(f"[CSRF] referer mismatch: referer={referer_host} host={host_header}", flush=True)
                return JSONResponse({"detail": "CSRF referer mismatch"}, status_code=403)
    if not validate_csrf_token(csrf_token, session_token):
        return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    import time
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    _request_logger.info("%s %s -> %s (%.0fms)", request.method, request.url.path, response.status_code, elapsed * 1000)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
# Mount uploads directory (local storage only)
from app.config import S3_ENABLED
if not S3_ENABLED:
    os.makedirs("uploads", exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Mount emoji directory (must be after the /emojis/{keyword} route)
_emoji_static_dir = os.path.join(os.path.dirname(__file__), "..", "web", "public", "emojis")

# AP/WebFinger routes must be registered before routers to take priority
@app.get("/.well-known/webfinger")
def webfinger(request: Request, resource: str = ""):
    if not resource or not resource.startswith("acct:"):
        return JSONResponse({"error": "Invalid resource"}, status_code=400)

    acct = resource[5:]
    if "@" in acct:
        username, domain = acct.split("@", 1)
        if domain != DOMAIN:
            return JSONResponse({"error": "Not found"}, status_code=404)
    else:
        username = acct

    # Handle both @domain and without
    username = username.replace(f"@{DOMAIN}", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)

    return JSONResponse({
        "subject": f"acct:{username}@{DOMAIN}",
        "aliases": [
            user.actor_uri(),
        ],
        "links": [
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": user.actor_uri(),
            },
            {
                "rel": "http://webfinger.net/rel/profile-page",
                "type": "text/html",
                "href": user.actor_uri(),
            },
        ],
    }, media_type="application/jrd+json")


@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    return RedirectResponse(url="/api/pwa/favicon", headers={"Cache-Control": "no-cache"})


@app.get("/users/{username}")
def user_actor(request: Request, username: str):
    accept = request.headers.get("Accept", "")

    session = get_session()
    try:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if getattr(user, 'is_deactivated', False):
            if "application/activity+json" in accept or "application/ld+json" in accept:
                return JSONResponse({"error": "Gone"}, status_code=410)
            raise HTTPException(status_code=410, detail="Account deleted")

        # If ActivityPub request, return actor JSON
        if "application/activity+json" in accept or "application/ld+json" in accept:
            return JSONResponse(content=user.to_ap_actor(),
                                media_type="application/activity+json")

        # Browser request — redirect to web frontend
        return RedirectResponse(url=f"{BASE_URL}/users/{username}")
    finally:
        session.close()


def _check_collection_access(username: str, request: Request) -> bool:
    """Check if the requester can view this user's ActivityPub collections."""
    with get_session() as s:
        user = s.query(User).filter_by(username=username).first()
        if not user:
            return False
        return True


@app.get("/users/{username}/outbox")
def user_outbox(request: Request, username: str, page: int = None):
    if not _check_collection_access(username, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = get_outbox(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@app.get("/users/{username}/followers")
def user_followers(request: Request, username: str, page: int = None):
    if not _check_collection_access(username, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = get_followers(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@app.get("/users/{username}/following")
def user_following(request: Request, username: str, page: int = None):
    if not _check_collection_access(username, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = get_following(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@app.get("/users/{username}/featured")
def user_featured(request: Request, username: str, page: int = None):
    from app.activitypub import get_featured
    if not _check_collection_access(username, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = get_featured(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


def _ap_post_visible(post, request, session):
    """Check if an AP post is visible to the requester.
    For non-AP requests, redirect to frontend handles visibility.
    For AP requests, public/unlisted/home are always visible.
    Followers-only/mention posts require a valid HTTP signature from a follower/mentioned user.
    """
    v = post.visibility or "public"
    if v in ("public", "unlisted", "home"):
        return True
    accept = request.headers.get("Accept", "")
    if "application/activity+json" not in accept and "application/ld+json" not in accept:
        return True
    ok, remote_actor = _verify_http_signature(request, b"", {})
    if not ok or not remote_actor:
        return False
    if v == "followers":
        if post.mentioned_user_ids and remote_actor.id in post.mentioned_user_ids:
            return True
        return session.query(Follow).filter_by(
            follower_id=remote_actor.id, following_id=post.author_id, accepted=True
        ).first() is not None
    if v == "mention":
        return post.mentioned_user_ids and remote_actor.id in post.mentioned_user_ids
    return False


def _verify_http_signature(request: Request, body: bytes, activity: dict) -> tuple[bool, object]:
    """Verify HTTP signature.
    Returns (ok, remote_actor_or_None).
    """
    signature_header = request.headers.get("Signature", "")
    if not signature_header:
        return (False, None)
    params = {}
    for part in signature_header.split(","):
        if "=" in part:
            key, _, val = part.partition("=")
            params[key.strip()] = val.strip().strip('"')
    key_id = params.get("keyId", "")
    headers_str = params.get("headers", "")
    sig_b64 = params.get("signature", "")
    if not key_id or not sig_b64:
        return (False, None)

    # Digest validation — skip for GET (no body)
    if body:
        digest_header = request.headers.get("Digest", "")
        if not digest_header:
            return (False, None)
        expected_b64 = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
        expected_hex = "SHA-256=" + hashlib.sha256(body).hexdigest()
        if digest_header not in (expected_b64, expected_hex):
            return (False, None)

    # Resolve the remote actor who signed
    actor_url = key_id.split("#")[0] if "#" in key_id else key_id
    print(f"[SIG] keyId={key_id} actor_url={actor_url}", flush=True)
    # First try: DB lookup without network
    with get_session() as s:
        remote_actor = s.query(User).filter_by(remote_url=actor_url).first()
        if not remote_actor or not remote_actor.public_key:
            for _u in s.query(User).filter_by(is_remote=False).all():
                if _u.actor_uri() == actor_url:
                    remote_actor = _u
                    break
        if not remote_actor or not remote_actor.public_key:
            act_actor = activity.get("actor", "")
            if isinstance(act_actor, list):
                act_actor = act_actor[0]
            if act_actor:
                remote_actor = s.query(User).filter_by(remote_url=act_actor).first()
                if not remote_actor or not remote_actor.public_key:
                    for _u in s.query(User).filter_by(is_remote=False).all():
                        if _u.actor_uri() == act_actor:
                            remote_actor = _u
                            break
        if not remote_actor or not remote_actor.public_key:
            remote_actor = None
    print(f"[SIG] db_lookup={'found' if remote_actor else 'miss'}", flush=True)

    if not remote_actor or not remote_actor.public_key:
        # Skip if recently failed
        _fail_ts = _actor_fail_cache.get(actor_url)
        if _fail_ts and (time.time() - _fail_ts) < _ACTOR_FAIL_TTL:
            print(f"[SIG] skip fetch (cached fail, {int(time.time() - _fail_ts)}s ago) for {actor_url}", flush=True)
            return (False, None)
        print(f"[SIG] trying network fetch for {actor_url}", flush=True)
        try:
            from app.config import BASE_URL
            if BASE_URL in actor_url:
                print(f"[SIG] skip self-fetch ({BASE_URL})", flush=True)
            else:
                import httpx as _httpx, datetime as _dt, time as _time, hashlib as _hl, base64 as _b64
                from urllib.parse import urlparse as _up
                from app.crypto_utils import sign_string, get_private_key
                from app.models import User as _Usr, get_session as _gs
                _parsed = _up(actor_url)
                _date = _dt.datetime.now(_dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                _created = int(_time.time())
                _ss = f"(request-target): get {_parsed.path}\nhost: {_parsed.netloc}\ndate: {_date}\n(created): {_created}"
                _headers = {"Accept": "application/activity+json", "Date": _date, "Host": _parsed.netloc}
                with _gs() as _s:
                    _signer = _s.query(_Usr).filter_by(is_remote=False).first()
                    if _signer:
                        _priv = get_private_key(_signer, SECRET_KEY)
                        _sig = sign_string(_ss, _priv)
                        _headers["Signature"] = f'keyId="{_signer.actor_uri()}#main-key",algorithm="hs2019",created="{_created}",headers="(request-target) host date (created)",signature="{_sig}"'
                _resp = _httpx.get(actor_url, headers=_headers, timeout=10, follow_redirects=True)
                print(f"[SIG] fetch status={_resp.status_code}", flush=True)
                if _resp.status_code == 200:
                    _data = _resp.json()
                    _pubkey = _data.get("publicKey", {}).get("publicKeyPem", "") if isinstance(_data, dict) else ""
                    print(f"[SIG] pubkey_len={len(_pubkey)}", flush=True)
                    if _pubkey:
                        class _Actor:
                            public_key = _pubkey
                            remote_url = actor_url
                            is_remote = True
                            @staticmethod
                            def actor_uri(): return actor_url
                        remote_actor = _Actor()
                        print(f"[SIG] using inline _Actor (pubkey_len={len(_pubkey)})", flush=True)
                else:
                    _actor_fail_cache[actor_url] = time.time()
                    print(f"[SIG] cached fail for {actor_url} (status={_resp.status_code})", flush=True)
        except Exception:
            pass
    if not remote_actor or not remote_actor.public_key:
        return (False, None)

    # Actor binding check — verify the signer matches activity.actor
    activity_actor = activity.get("actor")
    if isinstance(activity_actor, list):
        activity_actor = activity_actor[0]
    signer_uri = remote_actor.actor_uri() if not remote_actor.is_remote else remote_actor.remote_url
    print(f"[SIG] bind_check signer_uri={signer_uri} activity_actor={activity_actor}", flush=True)
    if not activity_actor:
        print(f"[SIG] bind_check FAIL (no activity_actor)", flush=True)
        return (False, None)
    if signer_uri != activity_actor:
        print(f"[SIG] bind_check FAIL (signer != actor)", flush=True)
        return (False, None)
    print(f"[SIG] bind_check OK", flush=True)

    # Domain check — activity id must be from actor's domain
    activity_id = activity.get("id", "")
    if activity_id:
        from urllib.parse import urlparse as _urlparse
        try:
            actor_domain = _urlparse(activity_actor).netloc
            id_domain = _urlparse(activity_id).netloc
            if actor_domain and id_domain and actor_domain != id_domain:
                print(f"[SIG] domain_check FAIL (actor_domain={actor_domain} != id_domain={id_domain})", flush=True)
                return (False, None)
        except Exception:
            pass

    # Date freshness check — 5분 window to prevent replay
    date_header = request.headers.get("Date", "")
    if date_header:
        try:
            date_tuple = email.utils.parsedate_tz(date_header)
            if date_tuple:
                date_dt = datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple), tz=datetime.timezone.utc)
                now = datetime.datetime.now(datetime.timezone.utc)
                diff = abs((now - date_dt).total_seconds())
                if diff > 300:
                    print(f"[SIG] date_freshness FAIL diff={diff}", flush=True)
                    return (False, None)
        except (ValueError, TypeError, OverflowError):
            print(f"[SIG] date_parse FAIL", flush=True)
            return (False, None)

    # Build signed string (Fix 7 — use original Host header, not rewritten one)
    path = request.url.path
    date = request.headers.get("Date", "")
    host_header = request.headers.get("Host", "")
    # Rewrite가 Host를 api:8000으로 변경하면 DOMAIN으로 대체
    if host_header in ("api:8000", "localhost:8000") or host_header.startswith("172."):
        from app.config import DOMAIN
        host_header = DOMAIN
    digest_val = request.headers.get("Digest", "")
    signed_parts = {
        "(request-target)": f"post {path}",
        "host": host_header,
        "date": date,
        "digest": digest_val,
    }
    method = request.method.lower()
    created_param = params.get("created", "")
    signed_lines = []
    for h in headers_str.split():
        h = h.strip()
        if h == "(request-target)":
            signed_lines.append(f"(request-target): {method} {path}")
        elif h in ("(request-created)", "(created)"):
            signed_lines.append(f"{h}: {created_param}")
        elif h in signed_parts:
            signed_lines.append(f"{h}: {signed_parts[h]}")
        else:
            val = request.headers.get(h, "")
            signed_lines.append(f"{h}: {val}")
    signed_string = "\n".join(signed_lines)
    print(f"[SIG] verifying signature... signed_string={repr(signed_string)[:200]}", flush=True)
    ok = verify_signature(signed_string, sig_b64, remote_actor.public_key)
    print(f"[SIG] verify={'OK' if ok else 'FAIL'}", flush=True)
    if not ok:
        print(f"[SIG] retrying with _resolve_actor force_refresh", flush=True)
        fresh = _resolve_actor(actor_url, force_refresh=True)
        if fresh and fresh.public_key:
            ok = verify_signature(signed_string, sig_b64, fresh.public_key)
            print(f"[SIG] retry verify={'OK' if ok else 'FAIL'}", flush=True)
            return (ok, fresh if ok else None)
    return (ok, remote_actor if ok else None)


@app.post("/inbox")
async def shared_inbox(request: Request):
    try:
        body = await request.body()
    except Exception:
        # 클라이언트가 중간에 연결을 끊었거나 데이터 수신 실패 시 조용히 무시
        return {"ok": False}
    if len(body) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Request body too large")
    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    client_ip = request.client.host if request.client else ""
    rate_key = f"inbox:{actor_url or client_ip}"
    if not _check_rate_limit(rate_key):
        return JSONResponse({"status": "error", "message": "Too many requests"}, status_code=429)
    ok, remote_actor = _verify_http_signature(request, body, activity)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=401)
    activity_id = activity.get("id", "")
    if activity_id:
        with get_session() as s:
            already = s.query(ProcessedActivity).filter_by(id=activity_id).first()
            if already:
                return JSONResponse({"status": 200, "message": "Already processed"})
            s.add(ProcessedActivity(id=activity_id))
            s.commit()
    import asyncio
    loop = asyncio.get_event_loop()
    status_code, message = await loop.run_in_executor(None, handle_inbox, activity)
    return JSONResponse({"status": status_code, "message": message}, status_code=200)


@app.post("/users/{username}/inbox")
async def user_inbox(request: Request, username: str):
    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Request body too large")
    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]

    # Activity ID uniqueness (prevent replay/double-processing)
    activity_id = activity.get("id", "")
    if activity_id:
        with get_session() as s:
            already = s.query(ProcessedActivity).filter_by(id=activity_id).first()
            if already:
                return JSONResponse({"status": "ok", "message": "Already processed"}, status_code=200)

    # Rate limiting — per actor + per IP + daily cap
    client_ip = request.client.host if request.client else ""
    actor_key = f"actor:{actor_url}" if actor_url else ""
    ip_key = f"ip:{client_ip}" if client_ip else ""
    daily_key = f"daily:{actor_key or ip_key}"
    if not _check_daily_limit(daily_key):
        return JSONResponse({"status": "error", "message": "Daily limit exceeded"}, status_code=429)
    for rk in [actor_key, ip_key]:
        if rk and (not _check_rate_limit(rk) or not _check_burst_limit(rk)):
            return JSONResponse({"status": "error", "message": "Too many requests"}, status_code=429)

    # Validate inbox destination — check to/cc includes this user
    to_list = activity.get("to", [])
    if isinstance(to_list, str):
        to_list = [to_list]
    cc_list = activity.get("cc", [])
    if isinstance(cc_list, str):
        cc_list = [cc_list]
    all_audiences = to_list + cc_list
    user_uri = user.actor_uri()
    atype = activity.get("type")
    if atype in ("Follow", "Delete", "Reject", "Accept", "Undo", "Vote", "Like", "Announce", "Block"):
        pass
    elif atype == "Flag":
        pass
    elif user_uri not in all_audiences and f"{user_uri}/followers" not in all_audiences:
        return JSONResponse({"status": "error", "message": "Not addressed to this user"}, status_code=403)

    # Verify HTTP Signature
    request.state.sign_as_user = user
    ok, remote_actor = _verify_http_signature(request, body, activity)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=401)

    # Validate required fields per activity type
    if not atype:
        return JSONResponse({"status": "error", "message": "Missing activity type"}, status_code=400)
    if not actor_url:
        return JSONResponse({"status": "error", "message": "Missing actor"}, status_code=400)
    if atype in ("Create", "Update") and not activity.get("object"):
        return JSONResponse({"status": "error", "message": "Missing object"}, status_code=400)
    if atype in ("Like", "Announce", "Undo") and not activity.get("object"):
        return JSONResponse({"status": "error", "message": "Missing object"}, status_code=400)

    # Follow target validation
    if atype == "Follow":
        target = activity.get("object", "")
        if isinstance(target, dict):
            target = target.get("id", "")
        if isinstance(target, str) and target != user.actor_uri():
            return JSONResponse({"status": "error", "message": "Follow target mismatch"}, status_code=403)

    # Object ownership check for Like/Announce/Undo (actor must be the one who created the original activity)
    if atype in ("Like", "Announce"):
        pass
    if atype == "Undo":
        object_data = activity.get("object", {})
        if isinstance(object_data, dict):
            obj_actor = object_data.get("actor", "")
            if isinstance(obj_actor, list):
                obj_actor = obj_actor[0]
            if obj_actor and obj_actor != actor_url:
                return JSONResponse({"status": "error", "message": "Undo actor mismatch"}, status_code=403)

    import sys
    # Record activity ID to prevent replay
    if activity_id:
        with get_session() as s:
            s.add(ProcessedActivity(id=activity_id))
            s.commit()

    import asyncio
    loop = asyncio.get_event_loop()
    status_code, message = await loop.run_in_executor(None, handle_inbox, activity)
    return JSONResponse({"status": status_code, "message": message}, status_code=200)


@app.get("/activities/follow/{follow_uuid}")
def get_follow_activity(request: Request, follow_uuid: str):
    from app.models import Follow, User, get_session
    accept = request.headers.get("Accept", "")
    if "application/activity+json" not in accept:
        return JSONResponse({"error": "Not found"}, status_code=404)
    with get_session() as session:
        activity_id = f"{BASE_URL}/activities/follow/{follow_uuid}"
        follow = session.query(Follow).filter_by(activity_id=activity_id).first()
        if not follow:
            raise HTTPException(status_code=404, detail="Not found")
        follower = session.query(User).get(follow.follower_id)
        following = session.query(User).get(follow.following_id)
        if not follower or not following:
            raise HTTPException(status_code=404, detail="Not found")
        obj = following.actor_uri() if following.is_remote else following.actor_uri()
        activity = {
            "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
            "id": activity_id,
            "type": "Follow",
            "actor": follower.actor_uri(),
            "object": obj,
            "to": [obj],
        }
        return JSONResponse(content=activity, media_type="application/activity+json")

@app.get("/activities/create/{post_id}")
def get_create_activity(request: Request, post_id: int):
    from app.models import Post, get_session
    accept = request.headers.get("Accept", "")
    if "application/activity+json" not in accept:
        return JSONResponse({"error": "Not found"}, status_code=404)
    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Not found")
        if not _ap_post_visible(post, request, session):
            raise HTTPException(status_code=404, detail="Not found")
        return JSONResponse(content=post.to_ap_create(),
                            media_type="application/activity+json")


@app.get("/posts/{post_id}")
def get_post(request: Request, post_id: int):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Not found")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            if not _ap_post_visible(post, request, session):
                raise HTTPException(status_code=404, detail="Not found")
            return JSONResponse(content=post.to_ap_note(),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"/post/{post_id}")


@app.get("/@{username}")
def get_user_by_handle(request: Request, username: str):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        if "@" in username:
            user = session.query(User).filter_by(username=username, is_remote=True).first()
        else:
            user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        if getattr(user, 'is_deactivated', False):
            if "application/activity+json" in accept or "application/ld+json" in accept:
                return JSONResponse({"error": "Gone"}, status_code=410)
            raise HTTPException(status_code=410, detail="Account deleted")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            return JSONResponse(content=user.to_ap_actor(),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"{BASE_URL}/profile/{username}")


@app.get("/likes/{like_uuid}")
def get_like(like_uuid: str):
    """Return a Like activity (dereferenceable URI)."""
    from app.models import Like, User, get_session
    ap_id = f"{BASE_URL}/likes/{like_uuid}"
    with get_session() as s:
        like = s.query(Like).filter_by(ap_id=ap_id).first()
        if not like:
            return JSONResponse({"error": "Not found"}, status_code=404)
        post = like.post
        actor = s.query(User).get(like.user_id)
        if not post or not actor:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse({
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": ap_id,
            "type": "Like",
            "actor": actor.actor_uri(),
            "object": post.ap_id,
            "_misskey_reaction": like.reaction or "★",
        }, media_type="application/activity+json")

@app.get("/emojis/{keyword}")
def get_emoji(keyword: str):
    """Return an Emoji activity (dereferenceable URI)."""
    from app.models import CustomEmoji, get_session
    from app.config import S3_ENABLED
    ap_id = f"{BASE_URL}/emojis/{keyword}"
    with get_session() as s:
        emoji = s.query(CustomEmoji).filter_by(keyword=keyword).first()
        if not emoji:
            return JSONResponse({"error": "Not found"}, status_code=404)
        sub = "remote" if emoji.domain or emoji.category == "remote" else "local"
        if S3_ENABLED:
            from app.utils.storage import get_storage
            try:
                storage = get_storage()
                url = storage.url(f"emojis/{sub}/{emoji.file_name}")
            except Exception:
                url = f"{BASE_URL}/emojis/{sub}/{emoji.file_name}"
        else:
            url = f"{BASE_URL}/emojis/{sub}/{emoji.file_name}"
        ext = emoji.file_name.rsplit(".", 1)[-1].lower() if "." in emoji.file_name else "png"
        mt = f"image/{ext}" if ext in ("png", "jpg", "jpeg", "gif", "webp", "svg") else "image/png"
        return JSONResponse({
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": ap_id,
            "type": "Emoji",
            "name": f":{keyword}:",
            "icon": {
                "type": "Image",
                "mediaType": mt,
                "url": url,
            },
        }, media_type="application/activity+json")

@app.get("/boosts/{boost_uuid}")
def get_boost(boost_uuid: str):
    """Return an Announce activity (dereferenceable URI)."""
    from app.models import Boost, User, get_session
    ap_id = f"{BASE_URL}/boosts/{boost_uuid}"
    with get_session() as s:
        boost = s.query(Boost).filter_by(ap_id=ap_id).first()
        if not boost:
            return JSONResponse({"error": "Not found"}, status_code=404)
        post = boost.post
        actor = s.query(User).get(boost.user_id)
        if not post or not actor:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse({
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": ap_id,
            "type": "Announce",
            "actor": actor.actor_uri(),
            "object": post.ap_id,
        }, media_type="application/activity+json")

@app.get("/@{username}/{number}")
def get_post_by_handle(request: Request, username: str, number: str):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        post = session.query(Post).filter_by(author_id=user.id, number=number).first()
        if not post:
            raise HTTPException(status_code=404, detail="Not found")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            if post.is_deleted:
                return JSONResponse(content=post.to_ap_note(),
                                    media_type="application/activity+json")
            if not _ap_post_visible(post, request, session):
                raise HTTPException(status_code=404, detail="Not found")
            return JSONResponse(content=post.to_ap_note(),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"/post/{post.id}")


@app.get("/@{username}/series/{number}")
def get_series_by_handle(request: Request, username: str, number: str):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        novel = session.query(Novel).filter_by(author_id=user.id, number=number).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Not found")

        return RedirectResponse(url=f"/series/{novel.id}")


@app.get("/nodeinfo/2.0")
def nodeinfo():
    with get_session() as session:
        now = datetime.datetime.now(datetime.timezone.utc)
        user_count = session.query(User).filter_by(is_remote=False).count()
        active_month = session.query(User).filter(
            User.is_remote == False,
            User.id.in_(session.query(Post.author_id).filter(Post.created_at > (now - datetime.timedelta(days=30))))
        ).count()
        active_halfyear = session.query(User).filter(
            User.is_remote == False,
            User.id.in_(session.query(Post.author_id).filter(Post.created_at > (now - datetime.timedelta(days=180))))
        ).count()
        local_post_count = session.query(Post).filter(Post.author.has(is_remote=False)).count()
        from app.models import ServerSetting
        settings = ServerSetting.get(session)
        server_name = settings.server_name or "WRIT"
        server_desc = getattr(settings, 'server_description', '') or ''
        open_reg = not (getattr(settings, 'require_invite', False) or False)

    return JSONResponse({
        "version": "2.0",
        "software": {
            "name": "writ",
            "version": "1.0.0",
            "repository": "https://github.com/fad0805/writ",
        },
        "protocols": ["activitypub"],
        "services": {"inbound": [], "outbound": []},
        "openRegistrations": open_reg,
        "usage": {
            "users": {"total": user_count, "activeHalfyear": active_halfyear, "activeMonth": active_month},
            "localPosts": local_post_count,
        },
        "metadata": {
            "nodeName": server_name,
            "nodeDescription": server_desc,
        },
    })


def _verify_session_cookie(request: Request) -> bool:
    """Verify session cookie is present and well-formed (basic auth check)."""
    token = request.cookies.get("session")
    if not token:
        return False
    try:
        import base64 as _b64
        decoded = _b64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        if len(parts) != 3:
            return False
        user_id = int(parts[0])
        expires = int(parts[1])
        import time as _t
        if expires <= _t.time():
            return False
        return True
    except Exception:
        return False


@app.get("/api/stream")
async def sse_stream(request: Request):
    if not _verify_session_cookie(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    add_queue(q)
    try:
        async def event_gen() -> AsyncGenerator[str, None]:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield payload
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
        return StreamingResponse(event_gen(), media_type="text/event-stream")
    finally:
        remove_queue(q)


@app.websocket("/api/v1/streaming")
async def websocket_stream(websocket: WebSocket):
    token = websocket.cookies.get("session")
    if not token:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    try:
        import base64 as _b64
        decoded = _b64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        if len(parts) != 3 or int(parts[2]) <= 0:
            await websocket.close(code=4001, reason="Unauthorized")
            return
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    await websocket.accept()
    ws_id, ws_q = add_ws()
    try:
        while True:
            try:
                payload = await asyncio.wait_for(ws_q.get(), timeout=30)
                await websocket.send_text(payload)
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"event": "ping"}))
    except Exception:
        pass
    finally:
        remove_ws(ws_id)


@app.get("/.well-known/nodeinfo")
def well_known_nodeinfo():
    return JSONResponse({
        "links": [
            {
                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "href": f"{BASE_URL}/nodeinfo/2.0",
            }
        ]
    })


if os.path.isdir(_emoji_static_dir):
    app.mount("/emojis", StaticFiles(directory=_emoji_static_dir), name="emojis")

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(api_router)


@app.get("/api/v1/instance")
def api_instance():
    with get_session() as session:
        user_count = session.query(User).filter_by(is_remote=False).count()
        post_count = session.query(Post).filter(Post.author.has(is_remote=False)).count()
    return JSONResponse({
        "uri": DOMAIN,
        "title": "SNS + Novel Blog",
        "description": "ActivityPub SNS with serial novel publishing blog",
        "version": "1.0.0",
        "urls": {
            "streaming_api": "",
        },
        "stats": {
            "user_count": user_count,
            "status_count": post_count,
            "domain_count": 0,
        },
        "thumbnail": "",
        "languages": ["ko"],
        "registrations": True,
        "short_description": "소설 연재가 가능한 ActivityPub SNS",
    })


# Run
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
