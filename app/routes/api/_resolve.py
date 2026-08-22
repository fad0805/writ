"""URL/remote-content resolution endpoints extracted from _core.py and _posts.py."""
import logging
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from app.core.activitypub import (
    _ap_fetch,
    _background_fetch_outbox,
    _fetch_and_save_ap_object,
    _fetch_remote_post,
    _get_instance_actor,
    _resolve_actor,
)
from app.core.auth import get_current_user, require_auth
from app.core.federation import _check_fetch_domain_allowed
from app.core.threads import spawn
from app.core.visibility import _can_view
from app.db.database import get_session
from app.models import Episode, Novel, Post, User
from app.routes.api._episodes import _episode_json
from app.routes.api._novels import _novel_json
from app.serializers import _post_json, _user_json
from app.utils.to_ap_serializer import to_ap_note

logger = logging.getLogger("writ.api.resolve")

resolve_router = APIRouter()


def _normalize_remote_post_url(url: str) -> str:
    """Web URL(/@user/id) → AP URL(/users/user/statuses/id) 형태로 정규화."""
    m = re.match(r'^(https?://[^/]+)/@(\w+(?:@\S+)?)/([\w-]+)(\?.*)?$', url)
    if m:
        return f"{m.group(1)}/users/{m.group(2)}/statuses/{m.group(3)}"
    if url.endswith("/activity"):
        return url[:-len("/activity")]
    return url


@resolve_router.get("/by-series-number/{username}/{number}")
def api_by_series_number(request: Request, username: str, number: str):
    user = get_current_user(request)
    with get_session() as s:
        author = s.query(User).filter_by(username=username).first()
        if not author:
            raise HTTPException(status_code=404, detail="User not found")
        novel = s.query(Novel).filter_by(author_id=author.id, number=number).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if novel.visibility == "private" and (not user or novel.author_id != user.id):
            raise HTTPException(status_code=404, detail="Novel not found")
        return {"id": novel.id}


@resolve_router.post("/fetch-series")
def api_fetch_series(request: Request, url: str = Form(...)):
    with get_session() as s:
        m = re.match(r"(?:https?://[^/]+)?/series/(\d+)$", url)
        if m:
            novel = s.query(Novel).filter_by(id=int(m.group(1))).first()
            if novel and novel.visibility != "private":
                author = s.query(User).get(novel.author_id)
                return {"type": "series", "novel": _novel_json(novel, s), "author": _user_json(author) if author else None}
        m = re.match(r"(?:https?://[^/]+)?/series/by-number/(\w+)/([a-f0-9]+)", url)
        if m:
            author = s.query(User).filter_by(username=m.group(1)).first()
            if author:
                novel = s.query(Novel).filter_by(author_id=author.id, number=m.group(2)).first()
                if novel and novel.visibility != "private":
                    return {"type": "series", "novel": _novel_json(novel, s), "author": _user_json(author)}
        m = re.match(r"(?:https?://[^/]+)?/series/@(\w+)/(\S+)", url)
        if m:
            author = s.query(User).filter_by(username=m.group(1)).first()
            if author:
                novel = s.query(Novel).filter_by(author_id=author.id, number=m.group(2)).first()
                if novel and novel.visibility != "private":
                    return {"type": "series", "novel": _novel_json(novel, s), "author": _user_json(author)}
        raise HTTPException(status_code=404, detail="Series not found")


@resolve_router.post("/fetch-episode")
def api_fetch_episode(request: Request, url: str = Form(...)):
    get_current_user(request)
    with get_session() as s:
        m = re.match(r"(?:https?://[^/]+)?/series/(\d+)/episodes/(\d+)", url)
        if m:
            novel = s.query(Novel).filter_by(id=int(m.group(1))).first()
            if not novel or novel.visibility == "private":
                raise HTTPException(status_code=404, detail="Episode not found")
            episode = s.query(Episode).filter_by(id=int(m.group(2)), novel_id=novel.id).first()
            if not episode or not episode.is_published:
                raise HTTPException(status_code=404, detail="Episode not found")
            author = s.query(User).get(novel.author_id)
            return {
                "type": "episode",
                "episode": _episode_json(episode),
                "novel": _novel_json(novel, s),
                "author": _user_json(author) if author else None,
            }
        m = re.match(r"(?:https?://[^/]+)?/series/@(\w+)/(\S+?)/episodes/(\d+)", url)
        if m:
            author = s.query(User).filter_by(username=m.group(1)).first()
            if author:
                novel = s.query(Novel).filter_by(author_id=author.id, number=m.group(2)).first()
                if novel and novel.visibility == "private":
                    raise HTTPException(status_code=404, detail="Episode not found")
                if novel:
                    episode = s.query(Episode).filter_by(id=int(m.group(3)), novel_id=novel.id).first()
                    if episode and episode.is_published:
                        return {
                            "type": "episode",
                            "episode": _episode_json(episode),
                            "novel": _novel_json(novel, s),
                            "author": _user_json(author) if author else None,
                        }
        raise HTTPException(status_code=404, detail="Episode not found")


@resolve_router.get("/by-number/{username}/{number}")
def api_by_number(request: Request, username: str, number: str):
    accept = request.headers.get("accept", "")
    with get_session() as s:
        author = s.query(User).filter_by(username=username).first()
        post = None
        if author:
            post = s.query(Post).filter_by(author_id=author.id, number=number).first()
        if not post:
            # 로컬에 없으면 원격 AP에서 가져오기 시도
            remote_user = None
            if author:
                remote_user = author
            elif "@" in username:
                parts = username.split("@", 1)
                uname, domain = parts[0], parts[1]
                remote_url = f"https://{domain}/users/{uname}"
                remote_user = _resolve_actor(remote_url, sign_as=_get_instance_actor(s))
            if remote_user and remote_user.remote_url:
                base = remote_user.remote_url.rsplit("/users/", 1)[0] if "/users/" in remote_user.remote_url else ""
                if base:
                    remote_post_url = f"{base}/users/{remote_user.username.split('@')[0]}/statuses/{number}"
                    signer = _get_instance_actor(s)
                    post = _fetch_remote_post(remote_post_url, signer, s)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        # ActivityPub 요청 → AP JSON 반환
        if "application/activity+json" in accept or "application/ld+json" in accept:
            from app.routes.ap import _tombstone
            if post.is_deleted:
                # 삭제된 글 전문 노출 금지: Tombstone으로 응답
                return JSONResponse(content=_tombstone(post), status_code=410,
                                    media_type="application/activity+json")
            if post.visibility not in ("public", "unlisted", "home"):
                raise HTTPException(status_code=403, detail="Not authorized")
            return JSONResponse(content=to_ap_note(post), media_type="application/activity+json")
        # 일반 요청 → 로그인 없이도 공개 게시글 조회 가능
        user = get_current_user(request)
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        return _post_json(post, s, user)


@resolve_router.post("/fetch-post")
def api_fetch_post(request: Request, url: str = Form(...)):
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    err = _check_fetch_domain_allowed(url)
    if err:
        raise HTTPException(status_code=403, detail=err)

    # 💡 로컬 DB에 이미 저장된 원격 게시물이라면 네트워크 요청 없이 바로 반환 (빠른 인용 로딩)
    try:
        normalized = _normalize_remote_post_url(url)
        with get_session() as s:
            existing = s.query(Post).options(
                selectinload(Post.author),
            ).filter(Post.ap_id.in_([url, normalized]), Post.is_deleted == False).first()
            if existing and _can_view(existing, user, s):
                return _post_json(existing, s, user)
    except Exception as e:
        logger.error("fetch-post DB check failed: %s", e, exc_info=True)

    data = _ap_fetch(url, user)
    logger.info("fetch-post url=%s data_is_none=%s", url, data is None)
    if not data:
        raise HTTPException(status_code=400, detail="Cannot fetch post")

    logger.info("fetch-post data type=%s keys=%s", data.get("type"), list(data.keys())[:10])
    obj = data.get("object", data)
    obj_type = data.get("type", "")
    if obj_type in ("Create", "Announce"):
        obj = obj.get("object", obj) if isinstance(obj, dict) else obj
        obj_type = obj.get("type", "") if isinstance(obj, dict) else ""
    logger.info("fetch-post obj_type=%s obj_keys=%s", obj_type, list(obj.keys())[:10] if isinstance(obj, dict) else type(obj))
    if obj_type in ("Person", "Application", "Service"):
        with get_session() as _us:
            actor = _resolve_actor(url, sign_as=user)
            if actor:
                return {"type": "user", "redirect": f"/@{actor.username}"}
        raise HTTPException(status_code=400, detail="Cannot resolve actor")
    if obj_type not in ("Note", "Article"):
        raise HTTPException(status_code=400, detail=f"Not a Note/Article (type={obj_type})")

    result = _fetch_and_save_ap_object(obj, user)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to save post")
    return result


@resolve_router.post("/fetch-actor")
def api_fetch_actor(request: Request, url: str = Form(...)):
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    err = _check_fetch_domain_allowed(url)
    if err:
        raise HTTPException(status_code=403, detail=err)

    # Normalize /@username to /users/username for DB lookup
    _p = urlparse(url)
    _db_url = url
    if "/@" in _p.path:
        _uname = _p.path.split("/@")[-1].strip("/")
        if _uname and "/" not in _uname:
            _db_url = f"{_p.scheme}://{_p.netloc}/users/{_uname}"

    # 로컬 DB에 이미 존재하는 유저인지 먼저 확인 (외부 네트워크 요청 회피)
    with get_session() as _s:
        local_user = _s.query(User).filter(or_(User.remote_url == url, User.remote_url == _db_url)).first()
        if local_user:
            spawn(_background_fetch_outbox, url, user.id, local_user.id)
            return _user_json(local_user)

    actor = _resolve_actor(url, force_refresh=False, sign_as=user)
    if not actor:
        raise HTTPException(status_code=400, detail="Cannot resolve actor")

    spawn(_background_fetch_outbox, url, user.id, actor.id)

    with get_session() as _s:
        _attached = _s.query(User).filter(or_(User.remote_url == url, User.remote_url == _db_url)).first()
        if not _attached:
            _attached = _s.query(User).get(actor.id)
        return _user_json(_attached)
