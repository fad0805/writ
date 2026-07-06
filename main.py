import hashlib
import json
import time
from collections import defaultdict
from typing import AsyncGenerator

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from eventbus import add_queue, remove_queue
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from urllib.parse import urlparse
from crypto_utils import verify_signature
from config import BASE_URL, DOMAIN, CORS_ORIGINS
from models import User, Follow, Post, get_session, init_db
from routes.auth import router as auth_router
from routes.sns import router as sns_router
from routes.admin import router as admin_router
from routes.api import router as api_router
from activitypub import (
    get_outbox, get_followers, get_following, handle_inbox
)

_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str) -> bool:
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    timestamps = _rate_limit_store[key]
    # Prune old entries
    _rate_limit_store[key] = [t for t in timestamps if t > window_start]
    if len(_rate_limit_store[key]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limit_store[key].append(now)
    return True

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_default_data()
    try:
        from routes.api import _cleanup_avatars
        _cleanup_avatars()
    except Exception:
        pass
    yield


def seed_default_data():
    from routes.auth import hash_password
    from crypto_utils import generate_keypair as gen_kp, encrypt_key
    from config import SECRET_KEY
    from models import Novel, Episode

    with get_session() as session:
        if session.query(User).filter_by(username="author1").first():
            return  # already seeded

        priv, pub = gen_kp()
        salt, hsh = hash_password("test1234")
        author1 = User(
            username="author1", display_name="소설가 author1",
            password_hash=salt + ":" + hsh,
            private_key=encrypt_key(priv, SECRET_KEY), public_key=pub,
            summary="소설을 쓰는 사람입니다 ✍️",
            role="user",
            email="author1@example.com",
            email_verified=True,
        )
        session.add(author1)
        session.flush()

        priv2, pub2 = gen_kp()
        salt2, hsh2 = hash_password("test1234")
        reader1 = User(
            username="reader1", display_name="독자 reader1",
            password_hash=salt2 + ":" + hsh2,
            private_key=encrypt_key(priv2, SECRET_KEY), public_key=pub2,
            summary="소설 읽는 걸 좋아합니다 📖",
            role="user",
            email="reader1@example.com",
            email_verified=True,
        )
        session.add(reader1)
        session.flush()

        priv3, pub3 = gen_kp()
        admin_password = "admin1234"
        salt3, hsh3 = hash_password(admin_password)
        admin_user = User(
            username="admin", display_name="관리자",
            password_hash=salt3 + ":" + hsh3,
            private_key=encrypt_key(priv3, SECRET_KEY), public_key=pub3,
            summary="서버 관리자입니다",
            role="admin",
            is_admin=True,
            email="admin@example.com",
            email_verified=True,
        )
        session.add(admin_user)
        session.flush()

        print(f"✅ Admin account created: admin / {admin_password}")

        # author1's posts
        p1 = Post(author_id=author1.id, content="안녕하세요, 소설을 시작합니다!", visibility="public", number="a1b2c3d4")
        p2 = Post(author_id=author1.id, content="오늘은 첫 번째 에피소드를 썼어요.", visibility="home", number="e5f6g7h8")
        session.add_all([p1, p2])

        # author1's novels
        novel1 = Novel(author_id=author1.id, title="판타지 세계로", description="이세계 판타지 소설입니다", tags="판타지,이세계")
        novel2 = Novel(author_id=author1.id, title="일상의 기록", description="일상물 에세이", tags="일상,에세이")
        session.add_all([novel1, novel2])
        session.flush()

        ep1 = Episode(novel_id=novel1.id, episode_number=1, title="프롤로그", content="모든 이야기는 그렇게 시작되었다...")
        ep2 = Episode(novel_id=novel1.id, episode_number=2, title="첫 만남", content="드디어 주인공이 나타났다.")
        session.add_all([ep1, ep2])

        # reader1 follows author1
        follow = Follow(follower_id=reader1.id, following_id=author1.id, accepted=True)
        session.add(follow)

        # reader1's post
        p3 = Post(author_id=reader1.id, content="재미있는 소설 추천 받아요!", visibility="public", number="i9j0k1l2")
        session.add(p3)

        # Set AP IDs
        user_map = {author1.id: author1, reader1.id: reader1, admin_user.id: admin_user}
        for post in [p1, p2, p3]:
            u = user_map.get(post.author_id)
            if u:
                post.ap_id = f"{BASE_URL}/@{u.username}/{post.number}"

        session.commit()

app = FastAPI(title="WRIT, the sns for writers", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
# Mount uploads directory (local storage only)
import os
from config import STORAGE_BACKEND
if STORAGE_BACKEND == "local":
    os.makedirs("uploads", exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# AP/WebFinger routes must be registered before routers to take priority
@app.get("/.well-known/webfinger")
def webfinger(resource: str = ""):
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
    })


@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return FileResponse('static/favicon.ico')


@app.get("/users/{username}")
def user_actor(request: Request, username: str):
    accept = request.headers.get("Accept", "")

    session = get_session()
    try:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # If ActivityPub request, return actor JSON
        if "application/activity+json" in accept or "application/ld+json" in accept:
            return JSONResponse(content=user.to_ap_actor(),
                                media_type="application/activity+json")

        # Browser request — redirect to web frontend
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"http://localhost:3000/users/{username}")
    finally:
        session.close()


def _check_collection_access(username: str, request: Request) -> bool:
    """Check if the requester can view this user's ActivityPub collections."""
    from models import User, Follow, get_session
    with get_session() as s:
        user = s.query(User).filter_by(username=username).first()
        if not user:
            return False
        if not user.is_locked:
            return True
        # For locked users, verify HTTP signature from a follower
        body = b""
        try:
            import json
            ok, actor = _verify_http_signature(request, body, {})
            if ok and actor:
                follow = s.query(Follow).filter_by(
                    follower_id=actor.id, following_id=user.id, accepted=True
                ).first()
                if follow:
                    return True
        except Exception:
            pass
        return False


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

    # Digest validation — mandatory for POST (has body)
    digest_header = request.headers.get("Digest", "")
    if not digest_header:
        return (False, None)
    expected = "SHA-256=" + hashlib.sha256(body).hexdigest()
    if digest_header != expected:
        return (False, None)

    # Resolve the remote actor who signed
    from activitypub import _resolve_actor
    actor_url = key_id.split("#")[0] if "#" in key_id else key_id
    remote_actor = _resolve_actor(actor_url)
    if not remote_actor or not remote_actor.public_key:
        return (False, None)

    # Actor binding check (Fix 1) — verify the signer matches activity.actor
    activity_actor = activity.get("actor")
    if isinstance(activity_actor, list):
        activity_actor = activity_actor[0]
    signer_uri = remote_actor.actor_uri() if not remote_actor.is_remote else remote_actor.remote_url
    if not activity_actor or signer_uri != activity_actor:
        return (False, None)

    # Date freshness check — ±30s window to prevent replay
    from datetime import datetime, timezone
    date_header = request.headers.get("Date", "")
    if date_header:
        try:
            date_dt = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            diff = abs((now - date_dt).total_seconds())
            if diff > 30:
                return (False, None)
        except (ValueError, TypeError):
            return (False, None)

    # Build signed string (Fix 7 — use request Host header, not keyId host)
    path = request.url.path
    date = request.headers.get("Date", "")
    host_header = request.headers.get("Host", "")
    digest_val = request.headers.get("Digest", "")
    signed_parts = {
        "(request-target)": f"post {path}",
        "host": host_header,
        "date": date,
        "digest": digest_val,
    }
    signed_lines = []
    for h in headers_str.split():
        h = h.strip()
        if h == "(request-target)":
            signed_lines.append(f"(request-target): post {path}")
        elif h in signed_parts:
            signed_lines.append(f"{h}: {signed_parts[h]}")
        else:
            val = request.headers.get(h, "")
            signed_lines.append(f"{h}: {val}")
    signed_string = "\n".join(signed_lines)
    ok = verify_signature(signed_string, sig_b64, remote_actor.public_key)
    if not ok:
        # Retry with forced actor re-fetch (key rotation)
        from activitypub import _resolve_actor
        fresh = _resolve_actor(actor_url, force_refresh=True)
        if fresh and fresh.public_key:
            ok = verify_signature(signed_string, sig_b64, fresh.public_key)
            return (ok, fresh if ok else None)
    return (ok, remote_actor if ok else None)


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

    # Rate limiting (Fix 6) — per actor + per IP
    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    client_ip = request.client.host if request.client else ""
    rate_key = f"inbox:{actor_url or client_ip}"
    if not _check_rate_limit(rate_key):
        return JSONResponse({"status": "error", "message": "Too many requests"}, status_code=429)

    # Validate inbox destination (Fix 11) — check to/cc includes this user
    to_list = activity.get("to", [])
    if isinstance(to_list, str):
        to_list = [to_list]
    cc_list = activity.get("cc", [])
    if isinstance(cc_list, str):
        cc_list = [cc_list]
    all_audiences = to_list + cc_list
    user_uri = user.actor_uri()
    if activity.get("type") in ("Follow", "Delete"):
        # Follow/Delete target the user directly, not via to/cc
        pass
    elif user_uri not in all_audiences and f"{user_uri}/followers" not in all_audiences:
        return JSONResponse({"status": "error", "message": "Not addressed to this user"}, status_code=403)

    ok, remote_actor = _verify_http_signature(request, body, activity)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=401)

    # Additional check for Delete (Fix 2) — verify actor owns the deleted post
    if activity.get("type") == "Delete":
        object_url = activity.get("object", "")
        if isinstance(object_url, dict):
            object_url = object_url.get("id", "")
        if object_url:
            with get_session() as session:
                post = session.query(Post).filter_by(ap_id=object_url).first()
                if post:
                    author_uri = post.author.actor_uri() if not post.author.is_remote else post.author.remote_url
                    actor_url = activity.get("actor")
                    if isinstance(actor_url, list):
                        actor_url = actor_url[0]
                    if author_uri != actor_url:
                        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    status_code, message = handle_inbox(activity)
    return JSONResponse({"status": status_code, "message": message}, status_code=200)


@app.get("/posts/{post_id}")
def get_post(request: Request, post_id: int):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Not found")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            return JSONResponse(content=post.to_ap_note(),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"/post/{post_id}")


@app.get("/@{username}")
def get_user_by_handle(request: Request, username: str):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            return JSONResponse(content=user.to_ap_actor(),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"http://localhost:3000/profile/{username}")


@app.get("/likes/{like_uuid}")
def get_like(like_uuid: str):
    """Return a Like activity (dereferenceable URI)."""
    from models import Like, User, get_session
    ap_id = f"{BASE_URL}/likes/{like_uuid}"
    with get_session() as s:
        like = s.query(Like).filter_by(ap_id=ap_id).first()
        if not like:
            return JSONResponse({"error": "Not found"}, status_code=404)
        post = like.post
        actor = s.query(User).get(like.user_id)
        if not post or not actor:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": ap_id,
            "type": "Like",
            "actor": actor.actor_uri(),
            "object": post.ap_id,
        }

@app.get("/boosts/{boost_uuid}")
def get_boost(boost_uuid: str):
    """Return an Announce activity (dereferenceable URI)."""
    from models import Boost, User, get_session
    ap_id = f"{BASE_URL}/boosts/{boost_uuid}"
    with get_session() as s:
        boost = s.query(Boost).filter_by(ap_id=ap_id).first()
        if not boost:
            return JSONResponse({"error": "Not found"}, status_code=404)
        post = boost.post
        actor = s.query(User).get(boost.user_id)
        if not post or not actor:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": ap_id,
            "type": "Announce",
            "actor": actor.actor_uri(),
            "object": post.ap_id,
        }

@app.get("/@{username}/{number}")
def get_post_by_handle(request: Request, username: str, number: str):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        post = session.query(Post).filter_by(author_id=user.id, number=number, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Not found")

        if "application/activity+json" in accept or "application/ld+json" in accept:
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
        user_count = session.query(User).count()
        post_count = session.query(Post).count()

    return JSONResponse({
        "version": "2.0",
        "software": {
            "name": "sns-novel-blog",
            "version": "1.0.0",
            "repository": "https://github.com/example/sns-novel-blog",
        },
        "protocols": ["activitypub"],
        "services": {"inbound": [], "outbound": []},
        "openRegistrations": True,
        "usage": {
            "users": {"total": user_count},
            "localPosts": post_count,
        },
        "metadata": {
            "nodeName": "SNS + Novel Blog",
            "nodeDescription": "ActivityPub SNS with serial novel publishing blog",
        },
    })


@app.get("/api/stream")
async def sse_stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    add_queue(queue)
    try:
        async def event_gen() -> AsyncGenerator[str, None]:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    yield payload
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
        return StreamingResponse(event_gen(), media_type="text/event-stream")
    finally:
        remove_queue(queue)


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


app.include_router(auth_router)
app.include_router(sns_router)
app.include_router(admin_router)
app.include_router(api_router)


@app.get("/api/v1/instance")
def api_instance():
    return JSONResponse({
        "uri": DOMAIN,
        "title": "SNS + Novel Blog",
        "description": "ActivityPub SNS with serial novel publishing blog",
        "version": "1.0.0",
        "urls": {
            "streaming_api": "",
        },
        "stats": {
            "user_count": 0,
            "status_count": 0,
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
