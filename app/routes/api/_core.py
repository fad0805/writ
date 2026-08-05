"""Core API endpoints — admin extracted to _admin.py."""
import re
import asyncio
import threading
from datetime import datetime, timezone
import uuid
import logging
import time
import httpx
import traceback

from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, or_, and_, func
from sqlalchemy.orm import selectinload
from urllib.parse import urlparse

from app.models import User, Post, Follow, Like, Boost, Bookmark, Novel, SeriesFollow, Tag, FederationBlock, AllowedServer, ServerSetting, ServerSetting
from app.utils.to_ap_serializer import to_ap_actor
from app.serializers import _post_json, _user_json
from app.config.settings import SECRET_KEY
from app.core.activitypub import _fetch_remote_post, broadcast_to_followers, _resolve_actor
from app.utils.http import validate_url
from app.core.timeline_stream import add_stream, remove_stream
from app.db.database import get_session
from app.db.mention_resolver import _federation_allowed, _resolve_remote_user
from app.routes.auth import require_auth, get_current_user
from app.routes.api._series import _apply_latest_activity_order, _novel_json, _load_novel_meta
from app.utils.crypto import get_private_key, sign_string
from app.utils.filter import _timeline_filter
from app.utils.storage import LocalStorage, get_storage

logger = logging.getLogger("writ.api")

router = APIRouter(prefix="/api")

TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


# ── Timeline API ──

@router.get("/timeline/stream")
async def api_timeline_stream(request: Request, tl_type: str = "home"):
    user = require_auth(request)
    if tl_type not in TIMELINE_LABELS:
        tl_type = "home"
    sid, q = add_stream(user.id, tl_type)
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
            remove_stream(sid)
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


def _broadcast_update_actor(user):
    """Deliver Update actor activity to remote followers (background thread)."""
    try:
        update = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{user.actor_uri()}#updates/{uuid.uuid4()}",
            "type": "Update",
            "actor": user.actor_uri(),
            "object": to_ap_actor(user),
        }
        broadcast_to_followers(user, update)
    except Exception as e:
        logger.error("Failed to broadcast Update actor: %s", e, exc_info=True)


@router.get("/search/series")
def api_search_series(request: Request, q: str = Query("")):
    user = get_current_user(request)
    query = q.strip()
    if not user:
        return {"series": []}
    with get_session() as s:
        qb = _apply_latest_activity_order(s.query(Novel).filter(
            or_(Novel.visibility.in_(["public", "unlisted"]), Novel.author_id == user.id)
        ), s)
        if query:
            qb = qb.filter(Novel.title.ilike(f"%{query}%"))
        novels = qb.limit(5).all()
        _novel_meta = _load_novel_meta(s, novels)
        return {"series": [_novel_json(n, s, _episode_meta=_novel_meta) for n in novels]}


@router.get("/search/tags")
def api_recent_tags(request: Request, q: str = Query("")):
    user = get_current_user(request)
    query = q.strip().lstrip("#")
    if not query or not user:
        return {"tags": []}
    with get_session() as s:
        recent_posts = s.query(Post).filter(
            Post.author_id == user.id,
            Post.tag_list.any(),
        ).order_by(desc(Post.created_at)).limit(50).all()
        tag_names: set[str] = set()
        for p in recent_posts:
            for t in (p.tag_list or []):
                if query.lower() in t.name.lower():
                    tag_names.add(t.name)
        ordered = sorted(tag_names, key=lambda n: n.lower().startswith(query.lower()), reverse=True)[:5]
        return {"tags": [{"name": t} for t in ordered]}


def _cleanup_avatars():
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        return
    with get_session() as s:
        used_urls = {u.profile_image for u in s.query(User).filter(User.profile_image != "").all()}
        used_urls |= {u.header_image for u in s.query(User).filter(User.header_image != "").all()}
    now = time.time()
    for path in ("avatars", "headers"):
        for key in storage.list_keys(path):
            url = storage.url(key)
            if url in used_urls:
                continue
            mtime = storage.mtime(key)
            if mtime is not None and now - mtime > 86400:
                storage.delete(key)


@router.get("/explore")
def api_explore(request: Request, limit: int = Query(20), offset: int = Query(0)):
    user = get_current_user(request)
    with get_session() as s:
        # 1. 포스트 메인 쿼리
        local_ids = s.query(User.id).filter_by(is_remote=False).subquery()
        posts = s.query(Post).options(
            selectinload(Post.author)
        ).filter(
            Post.author_id.in_(local_ids),
            Post.visibility == "public",
            Post.is_deleted == False,
            Post.in_reply_to_id == None,
            Post.author.has(User.is_suspended == False),
        ).order_by(
            desc(Post.created_at)
        ).offset(offset).limit(limit + 1).all()
        has_more = len(posts) > limit
        posts = posts[:limit]

        # 2. 사용자 활동(좋아요, 부스트, 북마크, 리액션, 부스터) 배치 로딩
        post_ids = {p.id for p in posts}
        for _p in posts:
            if _p.boost_of_id:
                post_ids.add(_p.boost_of_id)
        _liked_ids = _boosted_ids = _bookmarked_ids = set()
        _my_reaction_map = {}
        _reactions_map = {}
        _mentioned_users_map = {}
        _boost_originals = {}
        if post_ids:
            boost_pointer_ids = {p.boost_of_id for p in posts if p.boost_of_id}
            if boost_pointer_ids:
                for orig in s.query(Post).options(selectinload(Post.author)).filter(Post.id.in_(boost_pointer_ids), Post.is_deleted == False).all():
                    _boost_originals[orig.id] = orig
        if user and post_ids:
            _liked_ids = {l.post_id for l in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(post_ids)).all()}
            _boosted_ids = {b.post_id for b in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(post_ids)).all()}
            for l in s.query(Like.post_id, Like.reaction).filter(Like.user_id == user.id, Like.post_id.in_(post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[l.post_id] = l.reaction
            for pid, react, cnt in s.query(Like.post_id, func.coalesce(Like.reaction, "★"), func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all():
                if pid not in _reactions_map:
                    _reactions_map[pid] = {}
                _reactions_map[pid][react] = cnt
            all_mentioned_ids = set()
            for p in posts:
                if p.mentioned_user_ids:
                    all_mentioned_ids.update(p.mentioned_user_ids)
            if all_mentioned_ids:
                _mentioned_users = {}
                for _um in s.query(User).filter(User.id.in_(all_mentioned_ids)).all():
                    if _um.is_remote and _um.remote_url:
                        _name = _um.username.split("@")[0]
                        _domain = urlparse(_um.remote_url).hostname or ""
                        _mentioned_users[_um.id] = f"{_name}@{_domain}"
                    else:
                        _mentioned_users[_um.id] = _um.username
                for p in posts:
                    if p.mentioned_user_ids:
                        _mentioned_users_map[p.id] = [_mentioned_users.get(mid, "?") for mid in p.mentioned_user_ids if mid in _mentioned_users]
                    else:
                        _mentioned_users_map[p.id] = []

        # 3. 첫 페이지에서만 소설 목록 조회
        novels = []
        _followers_map = {}
        _novel_meta = {}
        if offset == 0:
            novels = _apply_latest_activity_order(s.query(Novel).options(
                selectinload(Novel.author),
                selectinload(Novel.tag_list),
            ).filter(
                Novel.visibility == "public",
                Novel.is_published == True,
            ), s).limit(20).all()
            if novels:
                novel_ids = [n.id for n in novels]
                for nid, cnt in s.query(SeriesFollow.novel_id, func.count(SeriesFollow.id)).filter(SeriesFollow.novel_id.in_(novel_ids)).group_by(SeriesFollow.novel_id).all():
                    _followers_map[nid] = cnt
            _novel_meta = _load_novel_meta(s, novels)

        return {
            "posts": [_post_json(p, s, user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids, _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map, _mentioned_users_map=_mentioned_users_map, _boost_originals=_boost_originals, _skip_emojis=True) for p in posts],
            "has_more": has_more,
            "novels": [_novel_json(n, s, _followers_map=_followers_map, _episode_meta=_novel_meta) for n in novels],
        }


@router.get("/search")
def api_search(request: Request, q: str = Query(""), author: str = Query("")):
    user = get_current_user(request)
    query = q.strip().lstrip("@").lstrip("#")
    if not query:
        return {"posts": [], "novels": [], "users": []}
    with get_session() as s:
        pattern = f"%{query}%"

        following_ids = []
        if user:
            following_ids = [f.following_id for f in s.query(Follow).filter_by(follower_id=user.id, accepted=True).all()]
        visible_author_ids = set(following_ids)
        if user:
            visible_author_ids.add(user.id)

        is_hashtag_search = q.strip().startswith("#")

        tag = None
        q_posts = None
        novels = []
        if is_hashtag_search:
            tag = s.query(Tag).filter_by(name=query.lower()).first()

            if tag:
                # 1. 포스트 쿼리
                q_posts = s.query(Post).options(selectinload(Post.author), selectinload(Post.parent)).filter(
                    and_(
                        Post.tag_list.any(name=tag.name),
                        Post.is_deleted == False,
                        Post.author.has(User.is_suspended == False),
                    )
                )
                # 2. 소설(Novel) 쿼리 💡 (오류 방지를 위해 tag가 확실히 있을 때만 돌도록 안으로 이동)
                novels = s.query(Novel).options(selectinload(Novel.author)).filter(
                    and_(
                        Novel.tag_list.any(name=tag.name),
                        Novel.is_published == True,
                        Novel.visibility != "private",
                    )
                ).order_by(desc(Novel.updated_at)).limit(20).all()

        else:
            q_posts = s.query(Post).options(selectinload(Post.author), selectinload(Post.parent)).filter(
                and_(
                    Post.content.ilike(pattern),
                    Post.is_deleted == False,
                    Post.author.has(User.is_suspended == False),
                )
            )

            novels = _apply_latest_activity_order(s.query(Novel).options(selectinload(Novel.author)).filter(
                or_(Novel.title.ilike(pattern), Novel.description.ilike(pattern)),
                Novel.is_published == True,
                Novel.visibility != "private",
            ), s).limit(20).all()

        posts = []
        if q_posts:
            if user:
                q_posts = q_posts.filter(
                    or_(
                        Post.author_id.in_(visible_author_ids),
                        Post.visibility.in_(["public", "home"]),
                    )
                )
            else:
                q_posts = q_posts.filter(Post.visibility.in_(["public", "home"]))

            if author:
                author_user = s.query(User).filter_by(username=author).first()
                if author_user:
                    q_posts = q_posts.filter(Post.author_id == author_user.id)

            posts = q_posts.order_by(desc(Post.created_at)).limit(100).all()

        if user:
            posts = _timeline_filter(posts, s, user, "federated", following_ids)[:20]
        else:
            posts = posts[:20]

        local_users = s.query(User).filter(
            User.is_remote == False,
            User.is_suspended == False,
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern)),
        ).limit(20).all()

        remote_users = s.query(User).filter(
            User.is_remote == True,
            User.is_suspended == False,
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern)),
        ).limit(10).all()

        all_users = list(local_users) + list(remote_users)

        # Check if the query contains a blocked/allowed domain (handles only, not URLs)
        blocked_domain = None
        handle, domain = None, None
        if not query.startswith("http") and "@" in query and "." in query:
            at_parts = query.split("@", 1)
            if len(at_parts) == 2 and at_parts[0] and at_parts[1]:
                handle, domain = at_parts[0].strip().lower(), at_parts[1].strip().lower()
        if domain:
            if not _federation_allowed(domain, s):
                blocked_domain = domain

        # If query is handle@domain and no remote match yet, try to resolve
        if handle and domain and not blocked_domain:
            already_found = any(
                u.is_remote and u.username.lower().startswith(f"{handle}@") and u.username.lower().endswith(f"@{domain}")
                for u in all_users
            )

            if not already_found:
                try:
                    threading.Thread(target=_resolve_remote_user, args=(query,), daemon=True).start()
                except Exception:
                    pass

        post_ids = {p.id for p in posts}
        for _p in posts:
            if _p.boost_of_id:
                post_ids.add(_p.boost_of_id)
        _liked_ids = _boosted_ids = _bookmarked_ids = set()
        _my_reaction_map = {}
        _reactions_map = {}
        _mentioned_users_map = {}
        _boost_originals = {}
        if post_ids:
            boost_pointer_ids = {p.boost_of_id for p in posts if p.boost_of_id}
            if boost_pointer_ids:
                for orig in s.query(Post).options(selectinload(Post.author)).filter(Post.id.in_(boost_pointer_ids), Post.is_deleted == False).all():
                    _boost_originals[orig.id] = orig
            all_mentioned_ids = set()
            for p in posts:
                if p.mentioned_user_ids:
                    all_mentioned_ids.update(p.mentioned_user_ids)
            if all_mentioned_ids:
                _mu = {}
                for _um in s.query(User).filter(User.id.in_(all_mentioned_ids)).all():
                    if _um.is_remote and _um.remote_url:
                        _name = _um.username.split("@")[0]
                        _domain = urlparse(_um.remote_url).hostname or ""
                        _mu[_um.id] = f"{_name}@{_domain}"
                    else:
                        _mu[_um.id] = _um.username
                for p in posts:
                    if p.mentioned_user_ids:
                        _mentioned_users_map[p.id] = [_mu.get(mid, "?") for mid in p.mentioned_user_ids if mid in _mu]
                    else:
                        _mentioned_users_map[p.id] = []
            else:
                for p in posts:
                    _mentioned_users_map[p.id] = []
        if user and post_ids:
            _liked_ids = {l.post_id for l in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(post_ids)).all()}
            _boosted_ids = {b.post_id for b in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(post_ids)).all()}
            for l in s.query(Like.post_id, Like.reaction).filter(Like.user_id == user.id, Like.post_id.in_(post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[l.post_id] = l.reaction
            for pid, react, cnt in s.query(Like.post_id, func.coalesce(Like.reaction, "★"), func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all():
                if pid not in _reactions_map:
                    _reactions_map[pid] = {}
                _reactions_map[pid][react] = cnt

        _novel_meta = _load_novel_meta(s, novels)

        result = {
            "posts": [_post_json(p, s, user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids, _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map, _mentioned_users_map=_mentioned_users_map, _boost_originals=_boost_originals) for p in posts],
            "novels": [_novel_json(n, s, _episode_meta=_novel_meta) for n in novels],
            "users": [_user_json(u) for u in all_users],
        }
        if blocked_domain:
            result["blocked_domain"] = blocked_domain
        return result


def _fetch_and_save_ap_object(obj, user, _visited=None, _depth=0):
    """Fetch a remote AP object, resolve its author, save to DB, return post.
    Also recursively fetches parent posts (thread ancestors) up to depth 5."""
    if _depth > 5:
        return None
    if _visited is None:
        _visited = set()

    # 1. 스레드 상위 글 역추적 로직 안전하게 실행
    in_reply_to = obj.get("inReplyTo", "")
    if isinstance(in_reply_to, dict):
        in_reply_to = in_reply_to.get("id", "")
    if in_reply_to and in_reply_to not in _visited:
        _visited.add(in_reply_to)
        parent_data = _ap_fetch(in_reply_to, user)
        if parent_data:
            parent_obj = parent_data.get("object", parent_data)
            # 💡 재귀 함수가 안전하게 마칠 수 있도록 단독 실행 확보
            try:
                _fetch_and_save_ap_object(parent_obj, user, _visited, _depth + 1)
            except Exception as e:
                print(f"[WARN] Failed to process parent post {in_reply_to}: {e}", flush=True)

    actor_url = obj.get("id")
    post = None
    # 2. 본문 페치 및 DB 저장 로직 수행
    with get_session() as session:
        try:
            post = _fetch_remote_post(actor_url, user, session, _depth)
            # 💡 페치가 성공했을 때만 확실하게 DB 세션 커밋을 보장
            if post:
                session.commit()
        except Exception as e:
            # 💡 단순 print 대신 에러가 발생한 정확한 라인과 원인을 추적하기 위해 traceback 추가
            print(f"[ERROR] Failed to fetch remote post from {actor_url}: {e}", flush=True)
            traceback.print_exc() 
            return None # 껍데기를 만들지 않도록 에러 시 None 리턴 구조로 방어

        if not post:
            return None
        return _post_json(post, session, user)


def _safe_httpx_get(url, headers=None, timeout=15, max_size=5*1024*1024):
    """HTTP GET with redirect validation and size limit."""
    if not validate_url(url):
        print(f"[SAFE_GET] blocked by validate_url url={url}", flush=True)
        return None
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    # Intercept redirects to validate each target
    original_send = client.send
    def _validated_send(request, **kwargs):
        if validate_url(str(request.url)):
            return original_send(request, **kwargs)
        raise httpx.InvalidURL(f"Blocked redirect to {request.url}")
    client.send = _validated_send
    try:
        resp = client.get(url, headers=headers)
        client.close()
        print(f"[SAFE_GET] url={url} status={resp.status_code} len={len(resp.content)}", flush=True)
        if resp.status_code != 200:
            return None
        if len(resp.content) > max_size:
            return None
        return resp
    except Exception:
        client.close()
        return None

def _ap_fetch(url, user):
    """Fetch a remote URL with HTTP Signature, return parsed JSON."""
    # Convert web URL /@username/id to AP URL /users/username/statuses/id
    original_url = url
    m = re.match(r'^(https?://[^/]+)/@(\w+(?:@\S+)?)/([\w-]+)(\?.*)?$', url)
    if m:
        base, username, status_id, query = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        url = f"{base}/users/{username}/statuses/{status_id}{query}"

    if not validate_url(url):
        return None

    def _sign_and_fetch(target_url, _depth=0):
        if _depth > 2:
            return None
        date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        parsed = urlparse(target_url)
        path_with_query = parsed.path or "/"
        if parsed.query:
            path_with_query += f"?{parsed.query}"
        signed_string = (
            f"(request-target): get {path_with_query}\n"
            f"host: {parsed.netloc}\n"
            f"date: {date_str}"
        )
        try:
            signature = sign_string(signed_string, get_private_key(user, SECRET_KEY))
        except Exception:
            return None
        signature_header = (
            f'keyId="{user.actor_uri()}#main-key",'
            f'headers="(request-target) host date",'
            f'signature="{signature}"'
        )
        headers = {
            "Accept": "application/activity+json",
            "Signature": signature_header,
            "Date": date_str,
            "Host": parsed.netloc,
        }
        resp = _safe_httpx_get(target_url, headers=headers)
        if not resp or resp.status_code != 200:
            print(f"[AP_FETCH] url={target_url} status={resp.status_code if resp else 'None resp'}", flush=True)
            return None
        ct = resp.headers.get("content-type", "")
        if "json" not in ct and "activity" not in ct:
            html = resp.text[:100000]
            alt_m = re.search(r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/activity\+json["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
            if not alt_m:
                alt_m = re.search(r'<link[^>]+type=["\']application/activity\+json["\'][^>]+rel=["\']alternate["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
            if not alt_m:
                alt_m = re.search(r'href=["\']([^"\']+)["\'][^>]*type=["\']application/activity\+json["\']', html, re.I)
            if alt_m:
                alt_url = alt_m.group(1)
                print(f"[AP_FETCH] HTML response, found alternate AP URL: {alt_url}", flush=True)
                return _sign_and_fetch(alt_url, _depth + 1)
            print(f"[AP_FETCH] HTML response, no alternate link found for {target_url}", flush=True)
            return None
        try:
            return resp.json()
        except Exception as e:
            print(f"[AP_FETCH] json error url={target_url}: {e}", flush=True)
            return None

    result = _sign_and_fetch(url)
    # Fallback: try original /@username/id URL if /users/.../statuses/... returned 404
    if not result and original_url != url:
        print(f"[AP_FETCH] fallback to original_url={original_url}", flush=True)
        result = _sign_and_fetch(original_url)
    print(f"[AP_FETCH] result_is_none={result is None} original={original_url} converted={url}", flush=True)
    return result

def _check_fetch_domain_allowed(url: str) -> str | None:
    """Return an error message if the URL's domain is federated-blocked, else None."""
    domain = urlparse(url).hostname or ""
    if domain:
        with get_session() as s:
            mode = ServerSetting.get(s).federation_mode or "blacklist"
            if mode == "whitelist":
                allowed = s.query(AllowedServer).filter_by(domain=domain).first()
                if not allowed:
                    return f"허용되지 않은 서버입니다: {domain}"
            else:
                blocked = s.query(FederationBlock).filter_by(domain=domain).first()
                if blocked:
                    reason = f" ({blocked.reason})" if blocked.reason else ""
                    return f"차단된 서버입니다{reason}: {domain}"
    return None


def _background_fetch_outbox(url: str, user_id: int, actor_id: int):
    with get_session() as s:
        user = s.query(User).get(user_id)
        actor = s.query(User).get(actor_id)
        if not user or not actor:
            return
        try:
            outbox_url = getattr(actor, "outbox_url", None) or getattr(actor, "endpoints", {}).get("sharedInbox", "")
            if not outbox_url:
                date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                parsed = urlparse(url)
                created = int(time.time())
                ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
                priv = get_private_key(user, SECRET_KEY)
                sig = sign_string(ss, priv)
                sig_header = f'keyId="{user.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
                headers = {"Accept": "application/activity+json", "Signature": sig_header, "Date": date, "Host": parsed.netloc}
                r = _safe_httpx_get(url, headers=headers)
                if r:
                    outbox_url = r.json().get("outbox", "")
            if outbox_url:
                parsed2 = urlparse(outbox_url)
                date2 = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                created2 = int(time.time())
                path2 = parsed2.path or "/"
                if parsed2.query:
                    path2 += f"?{parsed2.query}"
                priv = get_private_key(user, SECRET_KEY)
                ss2 = f"(request-target): get {path2}\nhost: {parsed2.netloc}\ndate: {date2}\n(created): {created2}"
                sig2 = sign_string(ss2, priv)
                sig_header2 = f'keyId="{user.actor_uri()}#main-key",algorithm="hs2019",created="{created2}",headers="(request-target) host date (created)",signature="{sig2}"'
                headers2 = {"Accept": "application/activity+json", "Signature": sig_header2, "Date": date2, "Host": parsed2.netloc}
                resp = _safe_httpx_get(f"{outbox_url}?page=1", headers=headers2)
                if resp:
                    outbox_data = resp.json()
                    for item in outbox_data.get("orderedItems", []):
                        try:
                            obj = item.get("object", item)
                            _fetch_and_save_ap_object(obj, actor)
                        except Exception:
                            pass
        except Exception:
            pass


@router.post("/fetch-actor")
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
            threading.Thread(target=_background_fetch_outbox, args=(url, user.id, local_user.id), daemon=True).start()
            return _user_json(local_user)

    actor = _resolve_actor(url, force_refresh=False, sign_as=user)
    if not actor:
        raise HTTPException(status_code=400, detail="Cannot resolve actor")

    threading.Thread(target=_background_fetch_outbox, args=(url, user.id, actor.id), daemon=True).start()

    with get_session() as _s:
        _attached = _s.query(User).filter(or_(User.remote_url == url, User.remote_url == _db_url)).first()
        if not _attached:
            _attached = _s.query(User).get(actor.id)
        return _user_json(_attached)

