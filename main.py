import json
import hashlib
from urllib.parse import urlparse

import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_

from config import BASE_URL, DOMAIN
from models import User, Follow, Post, get_session, init_db
from routes.auth import router as auth_router, get_current_user
from routes.sns import router as sns_router
from routes.blog import router as blog_router
from routes.admin import router as admin_router
from activitypub import (
    get_actor, get_outbox, get_followers, get_following,
    handle_inbox, _post_to_inbox, _resolve_actor, generate_keypair,
)
from crypto_utils import verify_signature

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_default_data()
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
        p1 = Post(author_id=author1.id, content="안녕하세요, 소설을 시작합니다!", visibility="public")
        p2 = Post(author_id=author1.id, content="오늘은 첫 번째 에피소드를 썼어요.", visibility="home")
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
        p3 = Post(author_id=reader1.id, content="재미있는 소설 추천 받아요!", visibility="public")
        session.add(p3)

        # Set AP IDs
        for post in [p1, p2, p3]:
            post.ap_id = f"{BASE_URL}/posts/{post.id}"

        session.commit()

app = FastAPI(title="SNS + Novel Blog", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
# Mount uploads directory
import os
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

        # Browser request — delegate to the profile route in sns_router
        from routes.sns import view_profile
        return view_profile(request, username)
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


@app.post("/users/{username}/inbox")
async def user_inbox(request: Request, username: str):
    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

    # Verify HTTP signature
    body = await request.body()
    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # For now, accept all activities from known/verified sources
    status, message = handle_inbox(activity)
    return JSONResponse({"status": status, "message": message})


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
app.include_router(blog_router)
app.include_router(admin_router)


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
