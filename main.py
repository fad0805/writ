import json
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
from config import BASE_URL, DOMAIN
from models import User, Follow, Post, get_session, init_db
from routes.auth import router as auth_router
from routes.sns import router as sns_router
from routes.admin import router as admin_router
from routes.api import router as api_router
from activitypub import (
    get_outbox, get_followers, get_following, handle_inbox
)

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
    from crypto_utils import generate_keypair as gen_kp
    from models import Novel, Episode

    with get_session() as session:
        if session.query(User).filter_by(username="author1").first():
            return  # already seeded

        priv, pub = gen_kp()
        salt, hsh = hash_password("test1234")
        author1 = User(
            username="author1", display_name="소설가 author1",
            password_hash=salt + ":" + hsh,
            private_key=priv, public_key=pub,
            summary="소설을 쓰는 사람입니다 ✍️",
        )
        session.add(author1)
        session.flush()

        priv2, pub2 = gen_kp()
        salt2, hsh2 = hash_password("test1234")
        reader1 = User(
            username="reader1", display_name="독자 reader1",
            password_hash=salt2 + ":" + hsh2,
            private_key=priv2, public_key=pub2,
            summary="소설 읽는 걸 좋아합니다 📖",
        )
        session.add(reader1)
        session.flush()

        priv3, pub3 = gen_kp()
        admin_password = "admin1234"
        salt3, hsh3 = hash_password(admin_password)
        admin_user = User(
            username="admin", display_name="관리자",
            password_hash=salt3 + ":" + hsh3,
            private_key=priv3, public_key=pub3,
            summary="서버 관리자입니다",
            is_admin=True,
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
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
# Mount uploads directory
import os
os.makedirs("uploads", exist_ok=True)
os.makedirs("uploads/avatars/local", exist_ok=True)
os.makedirs("uploads/avatars/remote", exist_ok=True)
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


@app.get("/users/{username}/outbox")
def user_outbox(request: Request, username: str, page: int = None):
    result = get_outbox(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@app.get("/users/{username}/followers")
def user_followers(request: Request, username: str, page: int = None):
    result = get_followers(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@app.get("/users/{username}/following")
def user_following(request: Request, username: str, page: int = None):
    result = get_following(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


def _verify_http_signature(request: Request, body: bytes, local_user: User) -> bool:
    signature_header = request.headers.get("Signature", "")
    if not signature_header:
        return False
    params = {}
    for part in signature_header.split(","):
        if "=" in part:
            key, _, val = part.partition("=")
            params[key.strip()] = val.strip().strip('"')
    key_id = params.get("keyId", "")
    headers_str = params.get("headers", "")
    sig_b64 = params.get("signature", "")
    if not key_id or not sig_b64:
        return False
    # Resolve the remote actor who signed
    from activitypub import _resolve_actor
    remote_actor = _resolve_actor(key_id.split("#")[0] if "#" in key_id else key_id)
    if not remote_actor or not remote_actor.public_key:
        return False
    # Build signed string
    parsed = urlparse(key_id.split("#")[0] if "#" in key_id else key_id)
    path = request.url.path
    date = request.headers.get("Date", "")
    digest = request.headers.get("Digest", "")
    signed_parts = {
        "(request-target)": f"post {path}",
        "host": parsed.netloc or request.headers.get("Host", ""),
        "date": date,
        "digest": digest,
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
    return verify_signature(signed_string, sig_b64, remote_actor.public_key)


@app.post("/users/{username}/inbox")
async def user_inbox(request: Request, username: str):
    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

    body = await request.body()
    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    skip_verify = activity.get("type") in ("Delete",)
    if not skip_verify and not _verify_http_signature(request, body, user):
        return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=401)

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
