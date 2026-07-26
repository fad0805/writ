"""Core API endpoints — admin extracted to _admin.py."""
import os
import base64
import csv
import re
import json
import io
import asyncio
from datetime import datetime, timedelta, timezone
import uuid
import logging
import secrets
import time
import httpx
import threading
import traceback
from uuid import uuid4
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key, Encoding, PublicFormat
from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse, Response, FileResponse
from PIL import Image
from sqlalchemy import desc, or_, and_, func, String, text, select
from sqlalchemy.orm import selectinload, Session, joinedload
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from urllib.parse import urlparse

from email.mime.text import MIMEText
import smtplib

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, EpisodeDraft, SeriesFollow, SeriesNotice, Tag, CustomEmoji, ProfileNote, Report, ServerRule, BlockedDomain, FederationBlock, AllowedServer, MutedServer, ServerSetting, AdminLog, UserMute, UserBlock, SeriesMute, KeywordMute, EpisodeView, PushSubscription, LoginSession, ServerSetting
from app.utils.to_ap_serializer import to_ap_note, to_ap_create, to_ap_actor
from app.serializers import _post_json, _user_json
from app.config.settings import BASE_URL, MAX_POST_LENGTH, SECRET_KEY, S3_ENABLED, APP_ENV, SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, INITIAL_OWNER_PASSWORD, SESSION_EXPIRE_DAYS
from app.core.activitypub import _fetch_remote_post, broadcast_to_followers, _post_to_inbox, _federation_allowed, _build_reactions, _resolve_actor, _send_delete_post, _send_flag, _send_accept, _send_reject, _get_instance_actor, _validate_url, _fetch_remote_count
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user, VAPID_PUBLIC_KEY
from app.core.timeline_stream import broadcast_post, add_stream, remove_stream, broadcast_refresh_notifs, add_notif_stream, remove_notif_stream, broadcast_reaction_update, add_post_stream, remove_post_stream, broadcast_notif_sound, broadcast_delete
from app.db.database import get_session, get_db
from app.db.mention_resolver import resolve_handles_to_ids
from app.routes.auth import require_auth, require_active_auth, get_current_user, hash_password, verify_password, create_session, get_session_key_from_cookie, delete_session_by_key
from app.utils.content_parser import process_post_content, extract_mentions
from app.utils.crypto import encrypt_key, get_private_key, generate_keypair, sign_string, generate_csrf_token
from app.utils.datetime import _fmt_dt
from app.utils.emoji import EMOJI_DIR, _refresh_emoji_cache_forcibly, _emoji_url, _load_emojis
from app.utils.filter import _timeline_filter
from app.utils.log import log_admin_action
from app.utils.post import _get_descendant_ids
from app.utils.storage import LocalStorage, get_storage



logger = logging.getLogger("writ.api")


router = APIRouter(prefix="/api")


ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogg", ".mov"}
ALLOWED_UPLOAD_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_AVATAR_SIZE = 5 * 1024 * 1024
MAX_VIDEO_SIZE = 26214400
IMAGE_MIME_PREFIXES = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/ico")
VIDEO_MIME_TYPES = {"video/mp4", "video/webm", "video/ogg", "video/quicktime"}


def _validate_upload(file: UploadFile, *, allow_video: bool = True, max_size: int = MAX_IMAGE_SIZE, label: str = "file"):
    ext = os.path.splitext(file.filename or "file")[1].lower() if file.filename else ""
    is_video = ext in ALLOWED_VIDEO_EXTENSIONS
    is_image = ext in ALLOWED_IMAGE_EXTENSIONS
    if not is_image and not (is_video and allow_video):
        raise HTTPException(status_code=400, detail=f"{label}: 지원하지 않는 파일 형식입니다")
    ct = (file.content_type or "").lower()
    if is_image and not any(ct.startswith(p) for p in IMAGE_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail=f"{label}: 이미지 MIME 타입이 올바르지 않습니다")
    if is_video and ct not in VIDEO_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"{label}: 비디오 MIME 타입이 올바르지 않습니다")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if is_video and size > MAX_VIDEO_SIZE:
        raise HTTPException(status_code=400, detail=f"{label}: 비디오 파일이 너무 큽니다 (최대 25MB)")
    if is_image and size > max_size:
        raise HTTPException(status_code=400, detail=f"{label}: 이미지 파일이 너무 큽니다 (최대 {max_size // (1024*1024)}MB)")
    return ext, is_image, is_video


def _can_view(post, viewer, session):
    if post.is_deleted:
        return False
    if viewer and post.author_id == viewer.id:
        return True
    v = post.visibility or "public"
    if v in ("public", "home"):
        return True
    if not viewer:
        return False
    if v == "followers":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return session.query(Follow).filter_by(
            follower_id=viewer.id, following_id=post.author_id, accepted=True
        ).first() is not None
    if v == "mention":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return False
    return True


TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


# ── Auth API ──



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


# ── User / Profile API ──



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
        return {"series": [_novel_json(n, s) for n in novels]}


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
        post_ids = [p.id for p in posts]
        _liked_ids = _boosted_ids = _bookmarked_ids = set()
        _my_reaction_map = {}
        _reactions_map = {}
        _booster_map = {}
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
            for bid, buid in s.query(Boost.post_id, Boost.user_id).filter(Boost.post_id.in_(post_ids)).order_by(desc(Boost.created_at)).all():
                if bid not in _booster_map:
                    _booster_map[bid] = buid
            if _booster_map:
                _booster_users = {u.id: u for u in s.query(User).filter(User.id.in_(set(_booster_map.values()))).all()}
                _booster_map = {pid: _booster_users.get(uid) for pid, uid in _booster_map.items()}
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

        return {
            "posts": [_post_json(p, s, user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids, _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map, _booster_map=_booster_map, _mentioned_users_map=_mentioned_users_map, _boost_originals=_boost_originals, _skip_emojis=True) for p in posts],
            "has_more": has_more,
            "novels": [_novel_json(n, s, _followers_map=_followers_map) for n in novels],
        }


@router.get("/search")
def api_search(request: Request, q: str = Query(""), author: str = Query("")):
    user = get_current_user(request)
    query = q.strip().lstrip("@").lstrip("#")
    if not query:
        return {"posts": [], "novels": [], "users": []}
    # Check if the query contains a blocked/allowed domain (handles only, not URLs)
    blocked_domain = None
    if not query.startswith("http") and "@" in query and "." in query:
        parts = query.split("@")
        if len(parts) == 2 and parts[1]:
            domain = parts[1].strip().lower()
            if domain:
                with get_session() as s_check:
                    mode = ServerSetting.get(s_check).federation_mode or "blacklist"
                    if mode == "whitelist":
                        allowed = s_check.query(AllowedServer).filter_by(domain=domain).first()
                        if not allowed:
                            blocked_domain = domain
                    else:
                        blocked = s_check.query(FederationBlock).filter_by(domain=domain).first()
                        if blocked:
                            blocked_domain = domain
    with get_session() as s:
        pattern = f"%{query}%"
        is_hashtag_search = q.strip().startswith("#")
        following_ids = []
        if user:
            following_ids = [f.following_id for f in s.query(Follow).filter_by(follower_id=user.id, accepted=True).all()]
        if is_hashtag_search:
            tag = s.query(Tag).filter_by(name=query.lower()).first()
            if tag:
                # 1. 포스트 쿼리
                q_posts = s.query(Post).options(selectinload(Post.author)).filter(
                    Post.tag_list.any(name=tag.name),
                    Post.is_deleted == False,
                    Post.author.has(User.is_suspended == False),
                )
                if user:
                    q_posts = q_posts.filter(
                        Post.visibility == "public"
                        | (Post.author_id.in_(following_ids) & Post.visibility.in_(["public", "home", "followers"]))
                        | (Post.author_id == user.id)
                        | Post.mentioned_user_ids.contains([user.id])
                    )
                else:
                    q_posts = q_posts.filter(Post.visibility == "public")
                if author:
                    author_user = s.query(User).filter_by(username=author).first()
                    if author_user:
                        q_posts = q_posts.filter(Post.author_id == author_user.id)
                posts = q_posts.order_by(desc(Post.created_at)).limit(60).all()
                if user:
                    posts = _timeline_filter(posts, s, user, "federated", following_ids)[:20]
                else:
                    posts = posts[:20]
            else:
                # 태그가 디비에 없으면 둘 다 깔끔하게 빈 리스트 처리
                posts = []
            if tag:
                # 2. 소설(Novel) 쿼리 💡 (오류 방지를 위해 tag가 확실히 있을 때만 돌도록 안으로 이동)
                novels = s.query(Novel).options(selectinload(Novel.author)).filter(
                    Novel.tag_list.any(name=tag.name),
                    Novel.is_published == True,
                    Novel.visibility != "private",
                ).order_by(desc(Novel.updated_at)).limit(20).all()
            else:
                # 태그가 디비에 없으면 둘 다 깔끔하게 빈 리스트 처리
                novels = []
        else:
            q_posts = s.query(Post).options(selectinload(Post.author)).filter(
                Post.content.ilike(pattern),
                Post.is_deleted == False,
                Post.author.has(User.is_suspended == False),
            )
            if user:
                q_posts = q_posts.filter(
                    Post.visibility == "public"
                    | (Post.author_id.in_(following_ids) & Post.visibility.in_(["public", "home", "followers"]))
                    | (Post.author_id == user.id)
                    | Post.mentioned_user_ids.contains([user.id])
                )
            else:
                q_posts = q_posts.filter(Post.visibility == "public")
            posts = q_posts.order_by(desc(Post.created_at)).limit(60).all()
            if user:
                posts = _timeline_filter(posts, s, user, "federated", following_ids)[:20]
            else:
                posts = posts[:20]
            novels = _apply_latest_activity_order(s.query(Novel).options(selectinload(Novel.author)).filter(
                or_(Novel.title.ilike(pattern), Novel.description.ilike(pattern)),
                Novel.is_published == True,
                Novel.visibility == "public",
            ), s).limit(20).all()
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
        # If query is handle@domain and no remote match yet, try to resolve
        if "@" in query and not blocked_domain:
            at_parts = query.split("@", 1)
            if len(at_parts) == 2 and at_parts[0] and at_parts[1]:
                r_handle, r_domain = at_parts[0].strip().lower(), at_parts[1].strip().lower()
                already_found = any(
                    u.is_remote and u.username.lower().startswith(f"{r_handle}@") and u.username.lower().endswith(f"@{r_domain}")
                    for u in all_users
                )
                if not already_found:
                    try:
                        urls = [
                            f"https://{r_domain}/users/{r_handle}",
                            f"https://{r_domain}/@{r_handle}",
                            f"https://{r_domain}/u/{r_handle}",
                            f"https://{r_domain}/profile/{r_handle}",
                        ]
                        resolved = None
                        for url in urls:
                            try:
                                resolved = _resolve_actor(url)
                                if resolved:
                                    break
                            except Exception:
                                continue
                        if not resolved:
                            wf = httpx.get(
                                f"https://{r_domain}/.well-known/webfinger?resource=acct:{r_handle}@{r_domain}",
                                timeout=5,
                            )
                            if wf.status_code == 200:
                                wf_data = wf.json()
                                for link in wf_data.get("links", []):
                                    if link.get("rel") == "self" and link.get("type", "").endswith("activity+json"):
                                        href = link.get("href", "")
                                        if href:
                                            resolved = _resolve_actor(href)
                                            break
                        if resolved:
                            refreshed = s.query(User).get(resolved.id)
                            if refreshed:
                                all_users.append(refreshed)
                    except Exception:
                        pass
        result = {
            "posts": [_post_json(p, s, user) for p in posts],
            "novels": [_novel_json(n, s) for n in novels],
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
    if not _validate_url(url):
        print(f"[SAFE_GET] blocked by _validate_url url={url}", flush=True)
        return None
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    # Intercept redirects to validate each target
    original_send = client.send
    def _validated_send(request, **kwargs):
        if _validate_url(str(request.url)):
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

    if not _validate_url(url):
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
def api_fetch_actor(request: Request, background_tasks: BackgroundTasks, url: str = Form(...)):
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
            background_tasks.add_task(_background_fetch_outbox, url, user.id, local_user.id)
            return _user_json(local_user)

    actor = _resolve_actor(url, force_refresh=False, sign_as=user)
    if not actor:
        raise HTTPException(status_code=400, detail="Cannot resolve actor")

    background_tasks.add_task(_background_fetch_outbox, url, user.id, actor.id)

    with get_session() as _s:
        _attached = _s.query(User).filter(or_(User.remote_url == url, User.remote_url == _db_url)).first()
        if not _attached:
            _attached = _s.query(User).get(actor.id)
        return _user_json(_attached)




from app.routes.api._series import _apply_latest_activity_order, _novel_json
