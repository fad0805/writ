"""Post, timeline, and interaction endpoints extracted from _core.py."""
import os
import re
import json
import logging
import time
import threading
import traceback
import asyncio
import secrets
import uuid
import httpx
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Form, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse, Response
from sqlalchemy import desc, or_, and_, func, String, text
from sqlalchemy.orm import selectinload, Session

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, Tag, CustomEmoji, Report, ServerRule, ServerSetting
from app.utils.to_ap_serializer import to_ap_note, to_ap_create
from app.serializers import _post_json, _user_json
from app.config.settings import BASE_URL, MAX_POST_LENGTH, SECRET_KEY, S3_ENABLED, APP_ENV
from app.core.activitypub import _fetch_remote_post, broadcast_to_followers, _post_to_inbox, _federation_allowed, _build_reactions, _resolve_actor, _send_delete_post, _send_flag, _get_instance_actor
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_post, add_stream, remove_stream, broadcast_refresh_notifs, broadcast_reaction_update, add_post_stream, remove_post_stream, broadcast_notif_sound, broadcast_delete
from app.db.database import get_session, get_db
from app.db.mention_resolver import resolve_handles_to_ids
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.utils.content_parser import process_post_content, extract_mentions
from app.utils.datetime import _fmt_dt
from app.utils.emoji import _emoji_url, _load_emojis
from app.utils.filter import _timeline_filter
from app.utils.post import _get_descendant_ids
from app.utils.storage import get_storage

from app.routes.api._core import _can_view, _ap_fetch, _fetch_and_save_ap_object, _check_fetch_domain_allowed
from app.routes.api._series import _novel_json, _episode_json
from app.routes.api._interactions import _json_array_has_user

logger = logging.getLogger("writ.api.posts")

posts_router = APIRouter()

TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


# ── Helpers ──

def _validate_media_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("https", ""):
        return False
    if parsed.scheme == "javascript" or parsed.scheme == "data":
        return False
    path = parsed.path.lower()
    allowed_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm"}
    ext = os.path.splitext(path)[1]
    return ext in allowed_ext


def _sync_post_tags(post, s):
    """Parse #hashtags from post content and sync with Tag model."""
    tags = set(re.findall(r'(?<!\w)#([\w_가-힣]+)', post.content))
    desired = {t.lower(): t for t in tags}
    current = {t.name: t for t in (post.tag_list or [])}
    for lower_name, display in desired.items():
        if lower_name in current:
            tag = current[lower_name]
            if tag.display_name != display:
                tag.display_name = display
        else:
            tag = s.query(Tag).filter_by(name=lower_name).first()
            if not tag:
                tag = Tag(name=lower_name, display_name=display)
                s.add(tag)
                s.flush()
            else:
                tag.display_name = display
            post.tag_list.append(tag)
    for name in set(current.keys()) - set(desired.keys()):
        tag = current[name]
        post.tag_list.remove(tag)


def _get_feed(user, tl_type, session, limit=10, offset=0):
    print(f"[feed] _get_feed uid={user.id if user else None} tl={tl_type} limit={limit} offset={offset}", flush=True)
    _base_opts = [selectinload(Post.author), selectinload(Post.parent)]
    # Cache following IDs for home/social (reused across main query + reply filter)
    _following_ids = None
    if user and tl_type in ("home", "social"):
        _following_ids = {row[0] for row in session.query(Follow.following_id).filter_by(
            follower_id=user.id, accepted=True
        ).all()}
        _following_ids.add(user.id)
    _local_ids = None
    if tl_type in ("social", "local"):
        _local_ids = session.query(User.id).filter_by(is_remote=False).subquery()
    _all_boosted_ids = set()
    if tl_type == "home":
        following_ids = list(_following_ids) if _following_ids else [user.id]
        all_boost_user_ids = list(set(following_ids) | {user.id})
        boosted_ids = list({row[0] for row in session.query(Boost.post_id).filter(
            Boost.user_id.in_(all_boost_user_ids),
        ).all()})
        _all_boosted_ids = set(boosted_ids)
        final = following_ids[:]
        _mentioned_self = _json_array_has_user(Post.mentioned_user_ids, user.id)
        posts = session.query(Post).options(*_base_opts).filter(
            or_(
                Post.author_id.in_(final),
                Post.id.in_(boosted_ids),
                and_(_mentioned_self, Post.visibility.in_(("followers", "mention", "home"))),
            ),
            Post.is_deleted == False,
            or_(Post.visibility != "home", Post.author_id.in_(final), _mentioned_self),
        ).order_by(desc(Post.created_at)).offset(offset).limit(limit + 1).all()
    elif tl_type == "social":
        following_ids = list(_following_ids) if _following_ids else [user.id]
        all_boost_user_ids = list(set(following_ids) | {user.id})
        boosted_ids = list({row[0] for row in session.query(Boost.post_id).filter(
            Boost.user_id.in_(all_boost_user_ids),
        ).all()})
        _all_boosted_ids = set(boosted_ids)
        posts = session.query(Post).options(*_base_opts).filter(
            or_(
                and_(
                    or_(Post.author_id.in_(following_ids), Post.id.in_(boosted_ids)),
                    Post.is_deleted == False,
                    or_(Post.visibility != "home", Post.author_id.in_(following_ids)),
                ),
                and_(Post.author_id.in_(_local_ids), Post.visibility == "public", Post.is_deleted == False),
            ),
        ).order_by(desc(Post.created_at)).offset(offset).limit(limit + 1).all()
    elif tl_type == "local":
        # 1. local 타임라인에서도 로컬 유저들의 부스트를 함께 고려하기 위해 부스트 ID 수집
        _local_user_ids = [row[0] for row in session.query(User.id).filter_by(is_remote=False).all()]
        boosted_ids = list({row[0] for row in session.query(Boost.post_id).join(Post, Boost.post_id == Post.id).filter(
            Boost.user_id.in_(_local_user_ids),
            Post.visibility == "public",
            Post.is_deleted == False
        ).all()})
        _all_boosted_ids = set(boosted_ids)

        # 2. 로컬 작성자의 글이거나, 로컬 유저가 부스트한(단, 원본이 퍼블릭인) 게시물 포함
        posts = session.query(Post).options(*_base_opts).filter(
            or_(
                Post.author_id.in_(_local_ids),
                Post.id.in_(boosted_ids),
            ),
            Post.visibility == "public",
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).offset(offset).limit(limit + 1).all()
    else:
        posts = session.query(Post).options(*_base_opts).filter(
            Post.visibility == "public",
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).offset(offset).limit(limit + 1).all()
    raw_total = len(posts)
    print(f"[feed] raw query: {raw_total} posts for tl={tl_type}", flush=True)
    posts = [p for p in posts if not (p.visibility == "mention" and p.is_dm and p.author_id != user.id and user.id not in (p.mentioned_user_ids or []))]
    print(f"[feed] after DM filter: {len(posts)} posts", flush=True)
    # Deduplicate: when both original and boost of the same post exist,
    # show the boost pointer (at its current timestamp) and skip the original.
    # This matches Mastodon behavior — a boost appears in timeline at boost time.
    boost_pointer_ids = {p.boost_of_id for p in posts if p.boost_of_id}
    boost_originals = {}
    if boost_pointer_ids:
        for orig in session.query(Post).options(selectinload(Post.author)).filter(Post.id.in_(boost_pointer_ids), Post.is_deleted == False).all():
            boost_originals[orig.id] = orig
    _boosted_originals_in_feed = set()

    deduped = []
    for p in posts:
        if p.boost_of_id:
            if p.boost_of_id not in boost_originals:
                continue
            if tl_type == "local" and (boost_originals[p.boost_of_id].visibility or "public") != "public":
                continue
            _boosted_originals_in_feed.add(p.boost_of_id)
            deduped.append(p)
        elif p.id not in _boosted_originals_in_feed:
            deduped.append(p)
    posts = deduped
    print(f"[feed] after dedup: {len(posts)} posts", flush=True)
    if _following_ids:
        try:
            posts = _timeline_filter(posts, session, user, tl_type, _following_ids, boosted_ids=_all_boosted_ids, boost_originals=boost_originals)
            print(f"[feed] after mention filter: {len(posts)} posts", flush=True)
        except Exception as e:
            logger.error("feed mention filter error: %s", e, exc_info=True)
    has_more = raw_total > limit
    print(f"[feed] has_more={has_more} (raw_total={raw_total}, after_filter={len(posts)}, limit={limit})", flush=True)
    posts = posts[:limit]
    # Batch-load user interaction data for all remaining posts
    post_ids = [p.id for p in posts]
    # Also include original post IDs referenced by boost pointers
    for _p in posts:
        if _p.boost_of_id and _p.boost_of_id not in post_ids:
            post_ids.append(_p.boost_of_id)
    if user and post_ids:
        _all_likes = session.query(Like).filter(
            Like.user_id == user.id, Like.post_id.in_(post_ids)
        ).all()
        _liked_ids = {l.post_id for l in _all_likes}
        _my_reaction_map = {l.post_id: l.reaction for l in _all_likes if l.reaction}
        _boosted_ids = {b.post_id for b in session.query(Boost.post_id).filter(
            Boost.user_id == user.id, Boost.post_id.in_(post_ids)
        ).all()}
        _bookmarked_ids = {bm.post_id for bm in session.query(Bookmark.post_id).filter(
            Bookmark.user_id == user.id, Bookmark.post_id.in_(post_ids)
        ).all()}
        _vote_map = {v.post_id: v.option_index for v in session.query(Vote).filter(
            Vote.user_id == user.id, Vote.post_id.in_(post_ids)
        ).all()}
        # Batch load latest boost per post
        _booster_map = {}
        _cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
        for b in session.query(Boost).filter(
            Boost.post_id.in_(post_ids), Boost.created_at > _cutoff
        ).order_by(Boost.created_at.desc()).all():
            if b.post_id not in _booster_map:
                _booster_map[b.post_id] = b.user_id
        if _booster_map:
            _booster_users = {u.id: u for u in session.query(User).filter(
                User.id.in_(set(_booster_map.values()))
            ).all()}
            _booster_map = {pid: _booster_users.get(uid) for pid, uid in _booster_map.items()}
        # Batch load reactions (GROUP BY in SQL)
        _reactions_map = {}
        _default_react = "★"
        _reaction_rows = session.query(
            Like.post_id, func.coalesce(Like.reaction, _default_react), func.count(Like.id)
        ).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all()
        for pid, react, cnt in _reaction_rows:
            if pid not in _reactions_map:
                _reactions_map[pid] = {}
            _reactions_map[pid][react] = cnt
        # Batch load mentioned users
        all_mentioned_ids = set()
        for p in posts:
            if p.mentioned_user_ids:
                all_mentioned_ids.update(p.mentioned_user_ids)
        _mentioned_users_map = {}
        if all_mentioned_ids:
            _mentioned_users = {}
            for _mu in session.query(User).filter(User.id.in_(all_mentioned_ids)).all():
                if _mu.is_remote and _mu.remote_url:
                    _name = _mu.username.split("@")[0]
                    _domain = urlparse(_mu.remote_url).hostname or ""
                    _mentioned_users[_mu.id] = f"{_name}@{_domain}"
                else:
                    _mentioned_users[_mu.id] = _mu.username
            for p in posts:
                if p.mentioned_user_ids:
                    _mentioned_users_map[p.id] = [_mentioned_users.get(mid, "?") for mid in p.mentioned_user_ids if mid in _mentioned_users]
                else:
                    _mentioned_users_map[p.id] = []
    else:
        _liked_ids = _boosted_ids = _bookmarked_ids = set()
        _vote_map = _my_reaction_map = _reactions_map = _booster_map = _mentioned_users_map = {}
    print(f"[feed] final: {len(posts)} posts returned, has_more={has_more}", flush=True)
    _timeline_emojis = [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(session)]
    return [_post_json(p, session, user, tl_type,
                       _liked_ids=_liked_ids, _boosted_ids=_boosted_ids,
                       _bookmarked_ids=_bookmarked_ids, _vote_map=_vote_map,
                       _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map,
                       _booster_map=_booster_map, _mentioned_users_map=_mentioned_users_map,
                       _boost_originals=boost_originals, _skip_emojis=True)
            for p in posts], has_more, _timeline_emojis


def _broadcast_federation(user_id, post_id, visibility, plain_content=''):
    """Deliver Create activity to remote followers (background thread)."""
    # 🌟 함수 전체를 감싸서 외부 변수 간섭을 완전히 차단합니다.
    with get_session() as ap_s:
        user = ap_s.query(User).filter_by(id=user_id).first()
        post = ap_s.query(Post).filter_by(id=post_id).first()
        if not user or not post:
            logger.warning(f"Broadcast aborted: user_id={user_id} or post_id={post_id} not found")
            return

        create_activity = to_ap_create(post)
        if visibility == "mention":
            _remote_mentioned = False
            if post.mentioned_user_ids:
                mu_users = ap_s.query(User).filter(
                    User.id.in_(post.mentioned_user_ids), User.is_remote == True
                ).all()
                for mu in mu_users:
                    inbox = mu.inbox_url
                    if not inbox:
                        continue
                    domain = mu.actor_uri().split("/")[2] if "//" in mu.actor_uri() else ""
                    if domain and not _federation_allowed(domain):
                        continue
                    _post_to_inbox(inbox, create_activity, user)
                    _remote_mentioned = True
            if not _remote_mentioned:
                broadcast_to_followers(user, create_activity)
            remote_handles = set(re.findall(r'@([a-zA-Z0-9_]+@[\w.-]+\.[a-zA-Z]{2,})', plain_content or ""))
            _resolved_handles = []
            for handle in remote_handles:
                remote_user = ap_s.query(User).filter(
                    User.username == handle, User.is_remote == True
                ).first()
                if remote_user:
                    _resolved_handles.append((handle, remote_user))
                    continue
                try:
                    r_name, r_domain = handle.split("@", 1)
                    if not _federation_allowed(r_domain):
                        continue
                    resolved = None
                    for url in [f"https://{r_domain}/@{r_name}", f"https://{r_domain}/users/{r_name}"]:
                        try:
                            resolved = _resolve_actor(url, sign_as=user)
                            if resolved:
                                break
                        except Exception:
                            continue
                    if not resolved:
                        wf = httpx.get(
                            f"https://{r_domain}/.well-known/webfinger?resource=acct:{handle}",
                            timeout=5,
                        )
                        if wf.status_code == 200:
                            for link in wf.json().get("links", []):
                                if link.get("rel") == "self" and link.get("type", "").endswith("activity+json"):
                                    href = link.get("href", "")
                                    if href:
                                        resolved = _resolve_actor(href, sign_as=user)
                                        break
                    if resolved:
                        remote_user = ap_s.query(User).get(resolved.id)
                except Exception:
                    pass
                if remote_user:
                    _resolved_handles.append((handle, remote_user))
            for handle, remote_user in _resolved_handles:
                inbox = remote_user.inbox_url
                if not inbox:
                    continue
                domain = remote_user.actor_uri().split("/")[2] if "//" in remote_user.actor_uri() else ""
                if domain and not _federation_allowed(domain):
                    continue
                _post_to_inbox(inbox, create_activity, user)
        else:
            broadcast_to_followers(user, create_activity)
            # 답글인 경우 부모 작성자의 리모트 팔로워에게도 전달
            if post.in_reply_to_id and post.parent:
                parent_author = post.parent.author
                if parent_author and parent_author.is_remote:
                    inbox = parent_author.inbox_url
                    if inbox and _federation_allowed(urlparse(inbox).hostname or ""):
                        _post_to_inbox(inbox, create_activity, user)
                elif parent_author and not parent_author.is_remote:
                    pf_follows = ap_s.query(Follow).filter(
                        Follow.following_id == parent_author.id,
                        Follow.follower.has(is_remote=True),
                    ).all()
                    for pf in pf_follows:
                        inbox = pf.follower.shared_inbox_url or pf.follower.inbox_url
                        if not inbox:
                            continue
                        domain = urlparse(inbox).hostname or ""
                        if domain and not _federation_allowed(domain):
                            continue
                        _post_to_inbox(inbox, create_activity, user)
            delivered_domains = set()
            _known_handles = {}
            _unknown_handles = set()
            if post.mentioned_user_ids:
                follower_ids = {f.following_id for f in ap_s.query(Follow).filter(
                    Follow.following_id == user.id,
                    Follow.follower.has(is_remote=True),
                ).all()}
                mu_users = ap_s.query(User).filter(
                    User.id.in_(post.mentioned_user_ids), User.is_remote == True
                ).all()
                for mu in mu_users:
                    if mu.id not in follower_ids:
                        inbox = mu.inbox_url
                        if not inbox:
                            continue
                        domain = mu.actor_uri().split("/")[2] if "//" in mu.actor_uri() else ""
                        if domain and not _federation_allowed(domain):
                            continue
                        _post_to_inbox(inbox, create_activity, user)
                        delivered_domains.add(domain)

            remote_handles = set(re.findall(r'@([a-zA-Z0-9_]+@[\w.-]+\.[a-zA-Z]{2,})', plain_content or ""))
            for handle in remote_handles:
                remote_user = ap_s.query(User).filter(
                    User.username == handle, User.is_remote == True
                ).first()
                if remote_user:
                    _known_handles[handle] = remote_user
                else:
                    _unknown_handles.add(handle)

            if _unknown_handles:
                for handle in _unknown_handles:
                    try:
                        r_name, r_domain = handle.split("@", 1)
                        if not _federation_allowed(r_domain):
                            continue
                        resolved = None
                        for url in [f"https://{r_domain}/@{r_name}", f"https://{r_domain}/users/{r_name}"]:
                            try:
                                resolved = _resolve_actor(url, sign_as=user)
                                if resolved:
                                    break
                            except Exception:
                                continue
                        if not resolved:
                            wf = httpx.get(
                                f"https://{r_domain}/.well-known/webfinger?resource=acct:{handle}",
                                timeout=5,
                            )
                            if wf.status_code == 200:
                                for link in wf.json().get("links", []):
                                    if link.get("rel") == "self" and link.get("type", "").endswith("activity+json"):
                                        href = link.get("href", "")
                                        if href:
                                            resolved = _resolve_actor(href, sign_as=user)
                                            break
                        if resolved:
                            remote_user = ap_s.query(User).get(resolved.id)
                            if remote_user:
                                _known_handles[handle] = remote_user
                    except Exception:
                        pass
            for handle, remote_user in _known_handles.items():
                inbox = remote_user.inbox_url
                if not inbox:
                    continue
                domain = remote_user.actor_uri().split("/")[2] if "//" in remote_user.actor_uri() else ""
                if domain and not _federation_allowed(domain):
                    continue
                _post_to_inbox(inbox, create_activity, user)
                delivered_domains.add(domain)


def _broadcast_timeline(post_json, author_id, visibility, is_dm):
    """Deliver post to connected timeline streams (background thread)."""
    try:
        broadcast_post(post_json, author_id, visibility, is_dm)
    except Exception as e:
        logger.error("Failed to broadcast timeline: %s", e, exc_info=True)


# ── Routes ──

@posts_router.get("/posts/{post_id}/stream")
async def api_post_stream(request: Request, post_id: int):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    sid, q = add_post_stream(post_id)
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
            remove_post_stream(sid)
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@posts_router.get("/timeline/{tl_type}")
def api_timeline(request: Request, tl_type: str, limit: int = Query(10), offset: int = Query(0), s: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if getattr(user, 'is_deactivated', False):
        return JSONResponse({"error": "Account deactivated"}, status_code=403)
    if tl_type not in TIMELINE_LABELS:
        tl_type = "home"
    feed, has_more, emojis = _get_feed(user, tl_type, s, limit=limit, offset=offset)
    return {"posts": feed, "timeline_type": tl_type, "has_more": has_more, "_emojis": emojis}


@posts_router.get("/posts/{post_id}")
def api_get_post(request: Request, post_id: int):
    # --- [추가 시작] ActivityPub 전용 inbox 처리 ---
    accept_header = request.headers.get("Accept", "")
    is_activitypub = "application/activity+json" in accept_header or "application/ld+json" in accept_header
    if is_activitypub:
        with get_session() as s:
            post = s.query(Post).filter_by(id=post_id).first()
            if not post:
                raise HTTPException(status_code=404, detail="Not Found")
            note = to_ap_note(post)
            return JSONResponse(content=note, media_type="application/activity+json")
    # --- [추가 끝] ---

    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    fetch_remote_url = None
    with get_session() as s:
        post = s.query(Post).options(
            selectinload(Post.author),
            selectinload(Post.parent).selectinload(Post.author),
        ).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=403, detail="Cannot view this post")
        result = _post_json(post, s, user)

        limit = min(int(request.query_params.get("reply_limit", 5)), 50)
        offset = int(request.query_params.get("reply_offset", 0))
        anc_limit = min(int(request.query_params.get("ancestor_limit", 5)), 50)
        anc_offset = int(request.query_params.get("ancestor_offset", 0))

        direct_count = s.query(Post).filter_by(in_reply_to_id=post_id, is_deleted=False).count()
        result["total_replies"] = direct_count

        descendant_ids = _get_descendant_ids(s, post_id, max_depth=5)
        result["total_descendants"] = len(descendant_ids)

        reply_ids = sorted(descendant_ids)[offset:offset + limit]
        if reply_ids:
            descendants = s.query(Post).options(
                selectinload(Post.author),
                selectinload(Post.parent),
            ).filter(Post.id.in_(reply_ids)).order_by(Post.created_at).all()
        else:
            descendants = []
        reply_id_set = set(reply_ids)
        _reply_liked_ids = _reply_boosted_ids = _reply_bookmarked_ids = set()
        if user and reply_id_set:
            _reply_liked_ids = set(r[0] for r in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(reply_id_set)).all())
            _reply_boosted_ids = set(r[0] for r in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(reply_id_set)).all())
            _reply_bookmarked_ids = set(r[0] for r in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(reply_id_set)).all())
        result["replies"] = [_post_json(r, s, user, _liked_ids=_reply_liked_ids, _boosted_ids=_reply_boosted_ids, _bookmarked_ids=_reply_bookmarked_ids) for r in descendants if _can_view(r, user, s)]
        result["has_more_replies"] = offset + limit < len(descendant_ids)

        ancestors = []
        cur = post.parent
        ancestor_ids = []

        max_depth = 100
        depth = 0
        while cur and depth < max_depth:
            if not cur.is_deleted:
                ancestor_ids.append(cur.id)
                depth += 1
            cur = cur.parent

        ancestor_ids.reverse()

        total_ancestors = len(ancestor_ids)
        has_more_ancestors = anc_offset + anc_limit < total_ancestors
        sliced_ids = ancestor_ids[anc_offset:anc_offset + anc_limit]

        if sliced_ids:
            if user:
                _anc_liked = {a[0] for a in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(sliced_ids)).all()}
                _anc_boosted = {a[0] for a in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(sliced_ids)).all()}
                _anc_bookmarked = {a[0] for a in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(sliced_ids)).all()}
            else:
                _anc_liked = _anc_boosted = _anc_bookmarked = set()

            sliced_posts = s.query(Post).options(
                selectinload(Post.author), selectinload(Post.parent),
            ).filter(Post.id.in_(sliced_ids)).all()
            sliced_map = {p.id: p for p in sliced_posts}

            for aid in sliced_ids:
                p = sliced_map.get(aid)
                if p and _can_view(p, user, s):
                    ancestors.append(_post_json(p, s, user, _liked_ids=_anc_liked, _boosted_ids=_anc_boosted, _bookmarked_ids=_anc_bookmarked))

        if not ancestors and not sliced_ids and post.in_reply_to_ap_id:
            parent = s.query(Post).filter_by(ap_id=post.in_reply_to_ap_id).first()
            if parent and _can_view(parent, user, s):
                ancestors = [_post_json(parent, s, user)]
            else:
                fetch_remote_url = post.in_reply_to_ap_id
        result["ancestors"] = ancestors
        result["has_more_ancestors"] = has_more_ancestors

    if fetch_remote_url:
        try:
            with get_session() as remote_s:
                remote_parent = _fetch_remote_post(fetch_remote_url, user, remote_s)
                # 💡 remote_parent가 정확히 존재하고(None이 아니고) 부모 게시글 객체일 때만 파싱하도록 방어막을 칩니다.
                if remote_parent is not None:
                    result["ancestors"] = [_post_json(remote_parent, remote_s, user)]
                else:
                    logger.warning("Remote parent fetch returned None for URL: %s", fetch_remote_url)
        except Exception as e:
            # 💡 pass로 에러를 완전히 지우지 말고, 개발 중에는 최소한 어떤 에러인지 로그를 남겨줍니다.
            logger.error("Failed to fetch or process remote parent: %s", e, exc_info=True)
    return result


@posts_router.post("/posts")
async def api_create_post(
    request: Request,
    content: str = Form(...),
    summary: str = Form(""),
    visibility: str = Form("public"),
    parent_id: int = Form(None),
    dm_target_id: int = Form(None),
    share_url: str = Form(""),
    media_attachments: str = Form("[]"),
    is_sensitive: bool = Form(False),
    poll_options: str = Form(""),
    poll_expires_in: int = Form(60),
    link_preview: str = Form(""),
):
    user = require_active_auth(request)
    loop = asyncio.get_running_loop()
    pj = await loop.run_in_executor(
        None, _do_create_post,
        user.id, user.is_limited, getattr(user, 'is_sensitive', False),
        content, summary, visibility, parent_id,
        dm_target_id, share_url, media_attachments, is_sensitive,
        poll_options, poll_expires_in, link_preview,
    )
    return pj


def _do_create_post(
    user_id, user_limited, user_sensitive, content, summary, visibility, parent_id,
    dm_target_id, share_url, media_attachments, is_sensitive,
    poll_options, poll_expires_in, link_preview,
):
    quote_of_ap_id = ""
    quote_of_id = None
    pending_quote_url = None
    if share_url:
        with get_session() as _qs:
            local = _qs.query(Post).filter(Post.ap_id == share_url).first()
            if local:
                quote_of_ap_id = local.ap_id
                quote_of_id = local.id
            else:
                pending_quote_url = share_url
    content_html = process_post_content(content, None)
    mentions = extract_mentions(content, None)
    mentioned_handles = [m["handle"] for m in mentions]
    mentioned_ids = resolve_handles_to_ids(mentioned_handles)
    if dm_target_id:
        mentioned_ids.append(dm_target_id)
    mentioned_ids = list(set(mentioned_ids))

    if not content_html.strip() and not poll_options:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    total_len = len(content) + len(summary)
    if total_len > MAX_POST_LENGTH:
        raise HTTPException(status_code=400, detail=f"Total length exceeds {MAX_POST_LENGTH}")
    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"

    if user_limited and visibility == "public":
        visibility = "home"

    if parent_id:
        vis_order = {"public": 0, "home": 1, "followers": 2, "mention": 3}
        with get_session() as _s:
            parent_post = _s.query(Post).filter_by(id=parent_id).first()
            if parent_post:
                parent_vis = parent_post.visibility or "public"
                if vis_order.get(parent_vis, 0) > vis_order.get(visibility, 0):
                    visibility = parent_vis

    with get_session() as s:
        _author = s.query(User).filter_by(id=user_id).first()
        if not _author:
            raise HTTPException(status_code=404, detail="User not found")
        post_number = secrets.token_hex(4)
        author_is_sensitive = user_sensitive
        if parent_id:
            _parent_exists = s.query(Post.id).filter_by(id=parent_id).first()
            if not _parent_exists:
                raise HTTPException(status_code=404, detail="부모 게시글이 삭제되었습니다.")
        post = Post(
            author_id=user_id,
            content=content_html,
            summary=summary,
            visibility=visibility,
            in_reply_to_id=parent_id,
            mentioned_user_ids=mentioned_ids,
            number=post_number,
            ap_id="",
            is_dm=bool(dm_target_id),
            is_sensitive=is_sensitive or author_is_sensitive,
            quote_of_ap_id=quote_of_ap_id,
            quote_of_id=quote_of_id,
        )
        if link_preview:
            try:
                post.link_preview = json.loads(link_preview)
            except (json.JSONDecodeError, TypeError):
                pass
        try:
            media = json.loads(media_attachments)
            if isinstance(media, list):
                cleaned = []
                for m in media[:16]:
                    if isinstance(m, str):
                        if _validate_media_url(m):
                            cleaned.append({"url": m, "type": "image", "alt": ""})
                    elif isinstance(m, dict) and _validate_media_url(m.get("url", "")):
                        cleaned.append({"url": m["url"], "type": m.get("type", "image"), "alt": m.get("alt", "")})
                post.media_attachments = cleaned
        except (json.JSONDecodeError, TypeError):
            pass
        if poll_options:
            try:
                opts = json.loads(poll_options)
                if isinstance(opts, list) and 2 <= len(opts) <= 10 and all(isinstance(o, str) and o.strip() for o in opts):
                    now = datetime.now(timezone.utc)
                    expires_at = (now + timedelta(minutes=poll_expires_in)).isoformat() if poll_expires_in > 0 else None
                    post.poll_data = {
                        "options": [{"text": o.strip(), "votes_count": 0} for o in opts],
                        "expires_at": expires_at,
                    }
            except (json.JSONDecodeError, TypeError):
                pass
        s.add(post)
        s.flush()
        post.ap_id = f"{BASE_URL}/@{_author.username}/{post.number}"
        _sync_post_tags(post, s)
        if parent_id:
            parent = s.query(Post).filter_by(id=parent_id).first()
            if parent:
                post.in_reply_to_ap_id = parent.ap_id or ""
        s.commit()

        def _create_notifications_and_broadcast():
            try:
                if pending_quote_url:
                    try:
                        with get_session() as _qs:
                            _signer = _qs.query(User).get(user_id)
                        if not _signer:
                            return
                        data = _ap_fetch(pending_quote_url, _signer)
                        if data:
                            obj = data.get("object", data)
                            if obj.get("type") in ("Note", "Article"):
                                result = _fetch_and_save_ap_object(obj, _signer)
                                if result:
                                    with get_session() as uqs:
                                        uqs.query(Post).filter_by(id=post.id).update({
                                            "quote_of_ap_id": result.ap_id, "quote_of_id": result.id
                                        })
                                        uqs.commit()
                    except Exception:
                        pass

                with get_session() as ns:
                    mentioned_notified = set()
                    for mu_id in mentioned_ids:
                        if mu_id != user_id:
                            notif = Notification(user_id=mu_id, from_user_id=user_id, notification_type="mention", post_id=post.id)
                            ns.add(notif)
                            mentioned_notified.add(mu_id)
                    if parent_id:
                        parent = ns.query(Post).filter_by(id=parent_id).first()
                        if parent and parent.author_id != user_id and parent.author_id not in mentioned_notified:
                            notif = Notification(user_id=parent.author_id, from_user_id=user_id, notification_type="reply", post_id=post.id)
                            ns.add(notif)
                    ns.commit()

                for mu_id in mentioned_ids:
                    if mu_id != user_id:
                        send_push_to_user(mu_id, "mention", _author.username, post.id)
                        broadcast_notif_sound(mu_id)
                        broadcast_refresh_notifs(mu_id)
                if parent_id:
                    with get_session() as ps:
                        parent = ps.query(Post).filter_by(id=parent_id).first()
                    if parent and parent.author_id != user_id and parent.author_id not in [mid for mid in mentioned_ids if mid != user_id]:
                        send_push_to_user(parent.author_id, "reply", _author.username, post.id)
                        broadcast_notif_sound(parent.author_id)
                        broadcast_refresh_notifs(parent.author_id)
            except Exception as e:
                logger.error("Failed to create notifications: %s", e, exc_info=True)

        threading.Thread(target=_create_notifications_and_broadcast, daemon=True).start()
        threading.Thread(target=_broadcast_federation, args=(user_id, post.id, visibility, content), daemon=True).start()

        try:
            broadcast("new_post", {"post_id": post.id, "author_id": user_id})
        except Exception as e:
            logger.error("Failed to broadcast new_post event: %s", e, exc_info=True)

        pj = _post_json(post, s, _author)
        threading.Thread(target=_broadcast_timeline, args=(pj, user_id, visibility, bool(dm_target_id)), daemon=True).start()
        return pj


@posts_router.post("/posts/{post_id}/edit")
def api_edit_post(request: Request, post_id: int, content: str = Form(...), summary: str = Form("")):
    user = require_active_auth(request)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id:
            raise HTTPException(status_code=403, detail="Cannot edit this post")
        if post.summary and post.summary.startswith("[관리자 강제] ") and not summary.startswith("[관리자 강제] "):
            raise HTTPException(status_code=403, detail="관리자가 강제한 CW는 수정할 수 없습니다")
        new_content = content.replace('\r\n', '\n').replace('\r', '\n')
        # 본문 파싱 및 시리즈/에피소드 외래키 자동 추출 연동
        post.content = process_post_content(new_content, post=post)
        post.summary = summary
        s.commit()

        # Broadcast update to local timeline streams
        try:
            _ua = post.author
            broadcast_post({
                "id": post.id,
                "number": post.number or "",
                "content": post.content,
                "summary": post.summary or "",
                "visibility": post.visibility or "public",
                "created_at": post.created_at.isoformat() if post.created_at else "",
                "author": {
                    "id": _ua.id, "username": _ua.username,
                    "display_name": _ua.display_name or _ua.username,
                    "avatar": _ua.profile_image or "", "header": _ua.header_image or "",
                    "summary": _ua.summary or "", "is_admin": _ua.is_admin,
                    "is_locked": getattr(_ua, "is_locked", False),
                    "is_limited": getattr(_ua, "is_limited", False),
                    "is_remote": _ua.is_remote, "ap_id": _ua.remote_url or "",
                },
                "likes_count": s.query(Like).filter_by(post_id=post.id).count(),
                "boosts_count": s.query(Boost).filter_by(post_id=post.id).count(),
                "replies_count": s.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                "poll_data": post.poll_data, "my_vote": None,
                "reactions": _build_reactions(s, post.id),
                "my_reaction": None,
                "type": "update",
                "_emojis": [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(s)],
            }, post.author_id, post.visibility or "public", False)
        except Exception:
            pass

        # Federation: send Update to remote followers
        if post.ap_id:
            try:
                note_data = to_ap_note(post)
                note_data.pop("@context", None)
                note_data.pop("url", None)
                note_data["atomUri"] = post.ap_id
                note_data["updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                note_data.setdefault("summary", None)
                note_data.setdefault("sensitive", False)
                note_data.setdefault("attachment", [])
                note_data.setdefault("tag", [])
                note_data.setdefault("inReplyTo", None)

                update_activity = {
                    "@context": [
                        "https://www.w3.org/ns/activitystreams",
                        "https://w3id.org/security/v1",
                    ],
                    "id": f"{BASE_URL}/activities/update/{post.id}",
                    "type": "Update",
                    "actor": user.actor_uri(),
                    "to": note_data.get("to", []),
                    "cc": note_data.get("cc", []),
                    "object": note_data,
                }
                def _send_update():
                    try:
                        broadcast_to_followers(user, update_activity)
                    except Exception as e:
                        # 🌟 logger.warning 대신 즉시 출력되도록 print flush 적용
                        logger.error("Update federation failed: %s", e, exc_info=True)
                threading.Thread(target=_send_update, daemon=True).start()
            except Exception as e:
                # 🌟 에러 로그 즉시 출력
                logger.error("Update activity build failed: %s", e, exc_info=True)

        return _post_json(post, s, user)


@posts_router.post("/posts/{post_id}/delete")
def api_delete_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id and not user.is_admin:
            raise HTTPException(status_code=403, detail="Cannot delete this post")
        media = list(post.media_attachments or [])
        ap_id = post.ap_id or ""
        is_remote_author = bool(post.author.is_remote)
        post.content = ""
        post.media_attachments = []
        post.poll_data = None
        post.link_preview = None
        post.is_deleted = True
        s.query(Notification).filter_by(post_id=post.id).delete()
        broadcast_refresh_notifs(post.author_id)
        s.flush()

        # Cascade purge: if parent shell's entire subtree is now all deleted, hard-delete it too
        def _all_deleted(pid):
            return not s.query(Post).filter(
                Post.in_reply_to_id == pid, Post.is_deleted == False
            ).first()

        _pid = post.id
        _cascade_authors = set()
        while True:
            _parent = s.query(Post).filter(Post.in_reply_to_id == _pid).first()
            if not _parent:
                # Check for the current post's parent
                if _pid == post.id:
                    _parent = s.query(Post).get(post.in_reply_to_id) if post.in_reply_to_id else None
                else:
                    _parent = s.query(Post).get(_pid)
            if not _parent or not _parent.is_deleted:
                break
            if not _all_deleted(_parent.id):
                break
            # All children of this parent are deleted → hard-delete the parent
            s.query(Like).filter(Like.post_id == _parent.id).delete()
            s.query(Boost).filter(Boost.post_id == _parent.id).delete()
            s.query(Bookmark).filter(Bookmark.post_id == _parent.id).delete()
            s.query(Vote).filter(Vote.post_id == _parent.id).delete()
            s.query(Notification).filter(Notification.post_id == _parent.id).delete()
            _cascade_authors.add(_parent.author_id)
            s.delete(_parent)
            _pid = _parent.in_reply_to_id
        s.commit()
    # Broadcast delete to all connected timeline streams
    try:
        broadcast_delete(post_id)
        for _aid in _cascade_authors:
            broadcast_refresh_notifs(_aid)
    except Exception:
        pass
    # Media 삭제 & AP 브로드캐스트는 백그라운드에서
    if media or (ap_id and ap_id.startswith("http") and not is_remote_author):
        def _background(_pid=post_id, _media=media, _ap_id=ap_id, _remote=is_remote_author, _user=user):
            if _media:
                storage = get_storage()
                for m in _media:
                    if isinstance(m, dict) and m.get("url"):
                        try:
                            storage.delete(m["url"])
                        except Exception:
                            pass
            if _ap_id and _ap_id.startswith("http") and not _remote:
                try:
                    with get_session() as _s:
                        p = _s.query(Post).get(_pid)
                        if p:
                            _send_delete_post(p, _user)
                        else:
                            print(f"DELETE_FAIL: post {_pid} not found in DB")
                except Exception as e:
                    logger.error("DELETE_FAIL: %s", e, exc_info=True)
        threading.Thread(target=_background, daemon=True).start()
    return {"ok": True}


@posts_router.post("/reports")
def api_create_report(request: Request, target_type: str = Form(...), target_id: int = Form(...), reason: str = Form(...), forward_to_remote: bool = Form(False), rule_ids: str = Form("")):
    user = require_active_auth(request)
    target_type = target_type.strip().lower()
    if target_type not in ("post", "novel", "episode"):
        raise HTTPException(status_code=400, detail="Invalid target_type")
    if forward_to_remote:
        _cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
        with get_session() as _s:
            _recent = _s.query(Report).filter(
                Report.reporter_id == user.id,
                Report.forward_to_remote == True,
                Report.created_at >= _cutoff,
            ).count()
            if _recent >= 3:
                raise HTTPException(status_code=429, detail="원격 신고는 1분에 3회까지 가능합니다")
    parsed_rule_ids = []
    if rule_ids and rule_ids.strip():
        try:
            parsed = json.loads(rule_ids)
            if isinstance(parsed, list):
                parsed_rule_ids = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if not reason or len(reason.strip()) < 10:
        if not parsed_rule_ids:
            raise HTTPException(status_code=400, detail="Reason must be at least 10 characters")
    with get_session() as s:
        existing = s.query(Report).filter_by(
            reporter_id=user.id, target_type=target_type, target_id=target_id, status="pending"
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Already reported")
        report = Report(reporter_id=user.id, target_type=target_type, target_id=target_id, reason=reason.strip(), forward_to_remote=forward_to_remote, rule_ids=parsed_rule_ids)
        s.add(report)
        s.flush()
        report_id = report.id
        admins = s.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
        target_label = ""
        target_author_name = ""
        target_obj = None
        if target_type == "post":
            target_obj = s.query(Post).filter_by(id=target_id).first()
            if target_obj:
                target_label = (target_obj.content or "")[:120]
                target_author_name = target_obj.author.username
        elif target_type == "novel":
            target_obj = s.query(Novel).filter_by(id=target_id).first()
            if target_obj:
                target_label = target_obj.title[:120]
                target_author_name = target_obj.author.username
        elif target_type == "episode":
            target_obj = s.query(Episode).filter_by(id=target_id).first()
            if target_obj:
                target_label = target_obj.title[:120]
                target_author_name = target_obj.novel.author.username if target_obj.novel else ""
        meta = {
            "type": "report",
            "report_id": report_id,
            "target_type": target_type,
            "target_id": target_id,
            "target_label": target_label,
            "target_author": target_author_name,
            "reason": reason.strip()[:200],
        }
        for admin in admins:
            if admin.id == user.id:
                continue
            s.add(Notification(
                user_id=admin.id, from_user_id=user.id,
                notification_type="moderation",
                metadata_json=json.dumps(meta),
            ))
        s.commit()
        for admin in admins:
            broadcast_refresh_notifs(admin.id)
        for admin in admins:
            if admin.id != user.id:
                send_push_to_user(admin.id, "moderation", user.username)
                broadcast_notif_sound(admin.id)

        if forward_to_remote and target_obj and hasattr(target_obj, 'author') and target_obj.author and target_obj.author.is_remote:
            try:
                _send_flag(user, target_type, target_obj, reason.strip()[:200], parsed_rule_ids)
            except Exception as e:
                logger.error("Failed to send Flag activity: %s", e, exc_info=True)
    return {"ok": True, "report_id": report_id}


@posts_router.get("/rules")
def api_list_rules():
    with get_session() as s:
        rules = s.query(ServerRule).order_by(ServerRule.sort_order).all()
        return [{"id": r.id, "title": r.title, "description": r.description, "sort_order": r.sort_order} for r in rules]


@posts_router.post("/posts/{post_id}/like")
def api_like_post(request: Request, background_tasks: BackgroundTasks, post_id: int, reaction: str = "★"):
    user = require_active_auth(request)
    if reaction.startswith(":") and reaction.endswith(":"):
        keyword = reaction[1:-1].strip().lower().replace(" ", "_")
        with get_session() as s:
            is_local_defined = s.query(CustomEmoji).filter_by(keyword=keyword, domain="").first()
            if not is_local_defined:
                raise HTTPException(status_code=400, detail=f"The emoji '{reaction}' is not registered on this server.")

    def _do_like():
        try:
            with get_session() as s:
                post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
                if not post:
                    return
                if not _can_view(post, user, s):
                    return
                existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                existing_notif = s.query(Notification).filter_by(
                    user_id=post.author_id, from_user_id=user.id, notification_type="like", post_id=post_id
                ).first() if post.author_id != user.id else None
                if not existing:
                    s.add(Like(user_id=user.id, post_id=post_id, reaction=reaction))
                    if post.author_id != user.id and not existing_notif:
                        _author_reactions = getattr(post.author, 'enable_reactions', True)
                        _notif_meta = {"reaction": reaction} if reaction and _author_reactions else {}
                        s.add(Notification(user_id=post.author_id, from_user_id=user.id, notification_type="like", post_id=post_id, metadata_json=json.dumps(_notif_meta) if _notif_meta else ""))
                    s.flush()
                    keep_id = s.query(Like.id).filter_by(user_id=user.id, post_id=post_id).order_by(Like.id.desc()).first()
                    if keep_id:
                        s.query(Like).filter(Like.user_id == user.id, Like.post_id == post_id, Like.id != keep_id[0]).delete(synchronize_session=False)
                    s.commit()
                    _reactions = {}
                    for _react, _cnt in s.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                        _reactions[_react or "★"] = _cnt
                    broadcast_reaction_update(post_id, _reactions)
                    if post.author_id != user.id:
                        broadcast_refresh_notifs(post.author_id)
                        send_push_to_user(post.author_id, "like", user.username, post_id)
                        broadcast_notif_sound(post.author_id)
                if post.author.is_remote and post.author.shared_inbox_url:
                    like_id = f"{BASE_URL}/likes/{uuid.uuid4()}"
                    like_rec = existing or s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                    if like_rec:
                        like_rec.ap_id = like_id
                        if reaction != "★":
                            like_rec.reaction = reaction
                        s.commit()
                    _react = reaction or "★"
                    is_custom = _react != "★"
                    activity_type = "EmojiReact" if is_custom else "Like"
                    like_activity = {
                        "@context": "https://www.w3.org/ns/activitystreams",
                        "id": like_id,
                        "type": activity_type,
                        "actor": user.actor_uri(),
                        "object": post.ap_id,
                        "to": [post.author.actor_uri()],
                        "cc": ["https://www.w3.org/ns/activitystreams#Public"],
                    }
                    if is_custom or _react:
                        like_activity["content"] = _react
                        like_activity["_misskey_reaction"] = _react
                    inbox = post.author.shared_inbox_url
                    try:
                        _post_to_inbox(inbox, like_activity, user)
                    except Exception:
                        pass
        except Exception:
            pass

    background_tasks.add_task(_do_like)
    return {"ok": True}


@posts_router.post("/posts/{post_id}/unlike")
def api_unlike_post(request: Request, background_tasks: BackgroundTasks, post_id: int):
    user = require_active_auth(request)

    def _do_unlike():
        try:
            with get_session() as s:
                post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
                if not post:
                    return
                existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                like_id = existing.ap_id if existing and existing.ap_id else ""
                existing_reaction = existing.reaction if existing else None
                if existing:
                    s.delete(existing)
                    s.query(Notification).filter_by(
                        from_user_id=user.id, notification_type="like", post_id=post_id
                    ).delete()
                    s.commit()
                    _reactions = {}
                    for _react, _cnt in s.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                        _reactions[_react or "★"] = _cnt
                    broadcast_reaction_update(post_id, _reactions)
                    broadcast_refresh_notifs(post.author_id)
                if post.author.is_remote and post.author.shared_inbox_url:
                    undo = {
                        "@context": "https://www.w3.org/ns/activitystreams",
                        "id": f"{BASE_URL}/likes/{uuid.uuid4()}#undo",
                        "type": "Undo",
                        "actor": user.actor_uri(),
                        "object": {
                            "id": like_id or f"{BASE_URL}/likes/{uuid.uuid4()}",
                            "type": "Like",
                            "actor": user.actor_uri(),
                            "object": post.ap_id,
                            "content": existing_reaction or "★",
                            "_misskey_reaction": existing_reaction or "★",
                        },
                    }
                    inbox = post.author.shared_inbox_url
                    try:
                        _post_to_inbox(inbox, undo, user)
                    except Exception:
                        pass
        except Exception:
            pass

    background_tasks.add_task(_do_unlike)
    return {"ok": True}


@posts_router.post("/posts/{post_id}/boost")
def api_boost_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        if post.boost_of_id:
            post = s.query(Post).get(post.boost_of_id)
            post_id = post.id
        if post.author_id != user.id and post.visibility in ("followers", "mention"):
            raise HTTPException(status_code=403, detail="Cannot boost followers-only or mention-only posts from other users")
        existing = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
        existing_notif = s.query(Notification).filter_by(
            user_id=post.author_id, from_user_id=user.id, notification_type="boost", post_id=post_id
        ).first() if post.author_id != user.id else None
        if not existing:
            s.add(Boost(user_id=user.id, post_id=post_id))
            # Create boost pointer post row
            boost_post = Post(
                author_id=user.id,
                content="",
                boost_of_id=post_id,
                visibility=post.visibility or "public",
            )
            s.add(boost_post)
            if post.author_id != user.id and not existing_notif:
                s.add(Notification(user_id=post.author_id, from_user_id=user.id, notification_type="boost", post_id=post_id))
            s.commit()
            # Stream the boost pointer post as a new timeline entry
            try:
                _a = post.author
                _author_json = _user_json(_a)
                _boosted_json = _user_json(user)
                _og = {
                    "id": post.id,
                    "number": post.number or "",
                    "content": post.content,
                    "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": _fmt_dt(post.created_at),
                    "author": _author_json,
                    "likes_count": 0,
                    "boosts_count": s.query(Boost).filter_by(post_id=post_id).count(),
                    "replies_count": post.replies_count or 0,
                    "liked": False, "boosted": True, "bookmarked": False,
                    "is_mine": True, "is_dm": False,
                    "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "",
                    "reply_context": None,
                    "boosted_by": _boosted_json,
                    "media_attachments": (post.media_attachments or []) if hasattr(post, 'media_attachments') else [],
                    "poll_data": None, "my_vote": None,
                    "reactions": {}, "my_reaction": None,
                    "mentioned_user_ids": [], "mentioned_handles": [],
                    "link_preview": None,
                    "_emojis": [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(s)],
                }
                _boost_user_id = user.id
                _boost_post_id = post_id
                def _safe_broadcast_boost_pointer():
                    with get_session() as _s:
                        if _s.query(Boost).filter_by(user_id=_boost_user_id, post_id=_boost_post_id).first():
                            _broadcast_timeline(_og, _boost_user_id, post.visibility or "public", False)
                threading.Thread(target=_safe_broadcast_boost_pointer, daemon=True).start()
            except Exception as e:
                logger.error("Failed to broadcast boost stream: %s", e, exc_info=True)
            # Also send an update event for the original post (count sync)
            try:
                broadcast_post({
                    "id": post.id, "type": "update",
                    "boosts_count": s.query(Boost).filter_by(post_id=post_id).count(),
                    "boosted_by": _user_json(user),
                }, post.author_id, post.visibility or "public", False)
            except Exception as e:
                logger.error("Failed to broadcast boost update: %s", e, exc_info=True)
            if post.author_id != user.id:
                broadcast_refresh_notifs(post.author_id)
                send_push_to_user(post.author_id, "boost", user.username, post_id)
                broadcast_notif_sound(post.author_id)

            # 1. Announce 활동(Activity) 페이로드 생성 (로컬/원격 글 공통)
            announce_id = f"{BASE_URL}/boosts/{uuid.uuid4()}"

            if post.author.is_remote and post.author.shared_inbox_url:
                boost_rec = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
                if boost_rec:
                    boost_rec.ap_id = announce_id
                    s.commit()

            announce = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": announce_id,
                "type": "Announce",
                "actor": user.actor_uri(),
                "object": post.ap_id,
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [
                    post.author.actor_uri(),
                    f'{BASE_URL}/users/{user.username}/followers'
                ],
            }

            # 2. 원격 작성자 본인에게 Announce 전송 (원격 글일 경우)
            if post.author.is_remote and post.author.shared_inbox_url:
                try:
                    threading.Thread(target=_post_to_inbox, args=(inbox, announce, user), daemon=True).start()
                except Exception as e:
                    logger.error("Failed to send boost to author inbox: %s", e, exc_info=True)

            # 3. 내 원격 팔로워들의 인박스로 Fan-out 전송
            try:
                followers = s.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == user.id).all()
                sent_inboxes = set()
                for follower in followers:
                    if follower.is_remote and (follower.shared_inbox_url or follower.inbox_url):
                        inbox = follower.shared_inbox_url or follower.inbox_url
                        if inbox not in sent_inboxes:
                            sent_inboxes.add(inbox)
                            try:
                                threading.Thread(target=_post_to_inbox, args=(inbox, announce, user), daemon=True).start()
                            except Exception as e:
                                logger.error("Failed to fan-out boost to inbox %s: %s", inbox, e, exc_info=True)
            except Exception as e:
                logger.error("Failed to query followers for boost fan-out: %s", e, exc_info=True)

        return {"ok": True}


@posts_router.post("/posts/{post_id}/bookmark")
def api_bookmark_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Bookmark).filter_by(user_id=user.id, post_id=post_id).first()
        if not existing:
            s.add(Bookmark(user_id=user.id, post_id=post_id))
            s.commit()
    return {"ok": True}


@posts_router.post("/posts/{post_id}/unbookmark")
def api_unbookmark_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(Bookmark).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            s.delete(existing)
            s.commit()
    return {"ok": True}


@posts_router.get("/bookmarks")
def api_bookmarks(request: Request, limit: int = Query(20), offset: int = Query(0)):
    user = require_active_auth(request)
    with get_session() as s:
        raw = s.query(Bookmark).filter_by(user_id=user.id).order_by(desc(Bookmark.created_at)).offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        posts = [_post_json(b.post, s, user) for b in raw[:limit] if b.post and not b.post.is_deleted and _can_view(b.post, user, s)]
        return {"posts": posts, "has_more": has_more}


@posts_router.get("/favorites")
def api_favorites(request: Request, limit: int = Query(10), offset: int = Query(0)):
    limit = min(limit, 20)
    user = require_active_auth(request)
    with get_session() as s:
        raw = s.query(Like).filter_by(user_id=user.id).order_by(desc(Like.created_at)).offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        posts = [_post_json(l.post, s, user) for l in raw[:limit] if l.post and not l.post.is_deleted and _can_view(l.post, user, s)]
        return {"posts": posts, "has_more": has_more}


@posts_router.post("/posts/{post_id}/unboost")
def api_unboost_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.boost_of_id:
            post = s.query(Post).get(post.boost_of_id)
            post_id = post.id
        existing = s.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
        announce_id = existing.ap_id if existing and existing.ap_id else ""
        if existing:
            s.delete(existing)
            # Delete boost pointer post
            s.query(Post).filter_by(author_id=user.id, boost_of_id=post_id).delete()
            s.query(Notification).filter_by(
                from_user_id=user.id, notification_type="boost", post_id=post_id
            ).delete()
            s.commit()
            if post.author_id != user.id:
                broadcast_refresh_notifs(post.author_id)
            # SSE: broadcast updated boosts_count (boosted_by cleared) for the original post.
            # The boost pointer post is serialized with the original post's id (see _post_json),
            # so clients see it as the original post with boosted_by set. Sending an update
            # event clears boosted_by and syncs the count across all connected timelines.
            try:
                broadcast_post({
                    "id": post_id, "type": "update",
                    "boosts_count": remaining,
                    "boosted_by": None,
                }, post.author_id, post.visibility or "public", False)
            except Exception as e:
                logger.error("Failed to broadcast unboost update: %s", e, exc_info=True)

            # 1. Undo 활동 페이로드 구성 (로컬/원격 글 공통)
            undo_id = f"{BASE_URL}/boosts/{uuid.uuid4()}#undo"
            target_announce_id = announce_id or f"{BASE_URL}/boosts/{uuid.uuid4()}"
            undo = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": undo_id,
                "type": "Undo",
                "actor": user.actor_uri(),
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [
                    post.author.actor_uri(),
                    f'{BASE_URL}/users/{user.username}/followers'
                ],
                "object": {
                    "id": target_announce_id,
                    "type": "Announce",
                    "actor": user.actor_uri(),
                    "object": post.ap_id,
                },
            }
            # 2. 원격 작성자 본인에게 Undo 전송 (원격 글일 경우)
            if post.author.is_remote and post.author.shared_inbox_url:
                try:
                    threading.Thread(target=_post_to_inbox, args=(post.author.shared_inbox_url, undo, user), daemon=True).start()
                except Exception as e:
                    logger.error("Failed to send unboost to author inbox: %s", e, exc_info=True)
            # 3. 내 팔로워들의 인박스로도 Undo를 뿌려주어 타임라인에서 취소 반영
            try:
                followers = s.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == user.id).all()
                sent_inboxes = set()
                for follower in followers:
                    if follower.is_remote and (follower.shared_inbox_url or follower.inbox_url):
                        inbox = follower.shared_inbox_url or follower.inbox_url
                        if inbox not in sent_inboxes:
                            sent_inboxes.add(inbox)
                            try:
                                _post_to_inbox(inbox, undo, user)
                            except Exception as e:
                                logger.error("Failed to fan-out unboost to inbox %s: %s", inbox, e, exc_info=True)
            except Exception as e:
                logger.error("Failed to query followers for unboost fan-out: %s", e, exc_info=True)
    return {"ok": True}



@posts_router.post("/posts/{post_id}/react")
def api_react_post(request: Request, background_tasks: BackgroundTasks, post_id: int, emoji: str = Form(...)):
    user = require_active_auth(request)
    with get_session() as s:
        settings = ServerSetting.get(s)
        if not emoji or len(emoji) > 50:
            raise HTTPException(status_code=400, detail="Invalid emoji")
        if emoji.startswith(":") and emoji.endswith(":"):
            _kw = emoji[1:-1]
            _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw, domain="").first()
            if not _emoji_row:
                _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw).first()
            if not _emoji_row or (_emoji_row.domain and _emoji_row.domain.strip()):
                raise HTTPException(status_code=400, detail="Remote emojis cannot be used as reactions")
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        reactions_disabled = not settings.enable_reactions or not getattr(post.author, 'enable_reactions', True)
        final_emoji = emoji if not reactions_disabled else None
        existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        old_reaction = existing.reaction if existing else None
        is_new = existing is None
        post_author_id = post.author_id
        post_ap_id = post.ap_id
        post_author_is_remote = post.author.is_remote
        post_author_shared_inbox = post.author.shared_inbox_url if post_author_is_remote else None
        post_author_actor = post.author.actor_uri() if post_author_is_remote else None
        post_author_enable_reactions = getattr(post.author, 'enable_reactions', True)

    def _do_react():
        try:
            with get_session() as s:
                post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
                if not post:
                    return
                existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                existing_notif = s.query(Notification).filter_by(
                    user_id=post_author_id, from_user_id=user.id, notification_type="like", post_id=post_id
                ).first() if post_author_id != user.id else None
                if existing:
                    existing.reaction = final_emoji
                    if post_author_id != user.id and existing_notif:
                        _notif_meta = {"reaction": final_emoji} if final_emoji and post_author_enable_reactions else {}
                        existing_notif.metadata_json = json.dumps(_notif_meta) if _notif_meta else ""
                else:
                    s.add(Like(user_id=user.id, post_id=post_id, reaction=final_emoji))
                    if post_author_id != user.id and not existing_notif:
                        _notif_meta = {"reaction": final_emoji} if final_emoji and post_author_enable_reactions else {}
                        s.add(Notification(user_id=post_author_id, from_user_id=user.id, notification_type="like", post_id=post_id, metadata_json=json.dumps(_notif_meta) if _notif_meta else ""))
                s.flush()
                keep_id = s.query(Like.id).filter_by(user_id=user.id, post_id=post_id).order_by(Like.id.desc()).first()
                if keep_id:
                    s.query(Like).filter(Like.user_id == user.id, Like.post_id == post_id, Like.id != keep_id[0]).delete(synchronize_session=False)
                s.commit()
                _reactions = {}
                for _react, _cnt in s.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                    _reactions[_react or "★"] = _cnt
                broadcast_reaction_update(post_id, _reactions)
                if post_author_id != user.id:
                    broadcast_refresh_notifs(post_author_id)
                if post_author_is_remote and post_author_shared_inbox:
                    _tag = []
                    if emoji.startswith(":") and emoji.endswith(":"):
                        _kw = emoji[1:-1]
                        _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw, domain="").first()
                        if not _emoji_row:
                            _emoji_row = s.query(CustomEmoji).filter_by(keyword=_kw).first()
                        if _emoji_row and _emoji_row.file_name:
                            _emoji_img = _emoji_url(_emoji_row.file_name, _emoji_row.domain or "", _emoji_row.category or "")
                            if not _emoji_img.startswith("http"):
                                _emoji_img = f"{BASE_URL}{_emoji_img}"
                        else:
                            _emoji_img = ""
                        if _emoji_img:
                            _tag = [{"type": "Emoji", "id": f"{BASE_URL}/emojis/{_kw}", "name": emoji, "icon": {"type": "Image", "mediaType": "image/png", "url": _emoji_img}}]
                    like_activity = {
                        "@context": "https://www.w3.org/ns/activitystreams",
                        "id": f"{BASE_URL}/likes/{uuid.uuid4()}",
                        "type": "Like",
                        "actor": user.actor_uri(),
                        "object": post_ap_id,
                        "content": emoji,
                        "_misskey_reaction": emoji,
                    }
                    if _tag:
                        like_activity["tag"] = _tag
                    if is_new or old_reaction != emoji:
                        try:
                            _post_to_inbox(post_author_shared_inbox, like_activity, user)
                        except Exception:
                            pass
        except Exception:
            pass

    background_tasks.add_task(_do_react)
    return {"ok": True}


@posts_router.post("/posts/{post_id}/unreact")
def api_unreact_post(request: Request, background_tasks: BackgroundTasks, post_id: int):
    user = require_active_auth(request)
    existing_reaction = None
    post_ap_id = ""
    post_author_is_remote = False
    post_author_shared_inbox = None
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        existing_reaction = existing.reaction if existing else None
        post_ap_id = post.ap_id
        post_author_is_remote = post.author.is_remote
        post_author_shared_inbox = post.author.shared_inbox_url if post_author_is_remote else None

    def _do_unreact():
        try:
            with get_session() as s:
                post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
                if not post:
                    return
                existing = s.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
                if existing:
                    s.delete(existing)
                    s.query(Notification).filter_by(
                        from_user_id=user.id, notification_type="like", post_id=post_id
                    ).delete()
                    s.commit()
                    _reactions = {}
                    for _react, _cnt in s.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                        _reactions[_react or "★"] = _cnt
                    broadcast_reaction_update(post_id, _reactions)
                    broadcast_refresh_notifs(post.author_id)
                    if post_author_is_remote and post_author_shared_inbox:
                        undo = {
                            "@context": "https://www.w3.org/ns/activitystreams",
                            "id": f"{BASE_URL}/likes/{uuid.uuid4()}#undo",
                            "type": "Undo",
                            "actor": user.actor_uri(),
                            "object": {
                                "id": f"{BASE_URL}/likes/{uuid.uuid4()}",
                                "type": "Like",
                                "actor": user.actor_uri(),
                                "object": post_ap_id,
                                "content": existing_reaction or "★",
                                "_misskey_reaction": existing_reaction or "★",
                            },
                        }
                        try:
                            _post_to_inbox(post_author_shared_inbox, undo, user)
                        except Exception:
                            pass
        except Exception:
            pass

    background_tasks.add_task(_do_unreact)
    return {"ok": True}


@posts_router.get("/posts/{post_id}/reaction-users")
def api_reaction_users(request: Request, post_id: int, emoji: str = ""):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        q = s.query(Like).filter(Like.post_id == post_id)
        if emoji == "★":
            q = q.filter((Like.reaction.is_(None)) | (Like.reaction == "★"))
        elif emoji:
            q = q.filter(Like.reaction == emoji)
        else:
            q = q.filter(Like.reaction.is_(None))
        like_rows = q.order_by(Like.id.desc()).limit(20).all()
        user_ids = list(dict.fromkeys(l.user_id for l in like_rows))
        if not user_ids:
            return {"users": []}
        users = {u.id: u for u in s.query(User).filter(User.id.in_(user_ids)).all()}
        return {"users": [_user_json(users[uid]) for uid in user_ids if uid in users]}


@posts_router.post("/posts/{post_id}/vote")
def api_vote_post(request: Request, post_id: int, option: int = Form(...)):
    user = require_active_auth(request)
    remote_vote_data = None
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        options = post.poll_data.get("options", [])
        if option < 0 or option >= len(options):
            raise HTTPException(status_code=400, detail="Invalid option")
        expires_at = post.poll_data.get("expires_at")
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
                    raise HTTPException(status_code=400, detail="Poll has ended")
            except (ValueError, TypeError):
                pass
        existing = s.query(Vote).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            old_option = existing.option_index
            if old_option == option:
                return {"ok": True}
            existing.option_index = option
        else:
            s.add(
                Vote(
                    user_id=user.id,
                    post_id=post_id,
                    option_index=option,
                    expires_at=post.poll_data.get("expires_at")
                )
            )
        s.flush()
        votes = s.query(Vote.option_index, func.count(Vote.id).label("cnt")).filter(Vote.post_id == post_id).group_by(Vote.option_index).all()
        counts = {v.option_index: v.cnt for v in votes}
        for i, opt in enumerate(options):
            opt["votes_count"] = counts.get(i, 0)
        s.query(Post).filter(Post.id == post_id).update({"poll_data": {**post.poll_data, "options": options}}, synchronize_session=False)
        s.flush()
        s.refresh(post)
        post_json = _post_json(post, s, user)
        if post.ap_id and post.author and post.author.is_remote:
            inbox = post.author.shared_inbox_url or post.author.inbox_url
            if inbox:
                remote_vote_data = (post.ap_id, post.author.actor_uri(), inbox, options[option]["text"])
        s.commit()
    if remote_vote_data:
        ap_id, author_uri, inbox, option_text = remote_vote_data
        vote_activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{BASE_URL}/votes/{uuid4()}/activity",
            "type": "Create",
            "actor": user.actor_uri(),
            "object": {
                "id": f"{BASE_URL}/votes/{uuid4()}",
                "type": "Note",
                "name": option_text,
                "attributedTo": user.actor_uri(),
                "to": [author_uri],
                "inReplyTo": ap_id,
            },
            "to": [author_uri],
        }
        try:
            _post_to_inbox(inbox, vote_activity, user)
        except Exception:
            pass
    return {"ok": True, "post": post_json}


@posts_router.post("/posts/{post_id}/unvote")
def api_unvote_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Vote).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            options = post.poll_data.get("options", [])
            s.delete(existing)
            s.flush()
            votes = s.query(Vote.option_index, func.count(Vote.id).label("cnt")).filter(Vote.post_id == post_id).group_by(Vote.option_index).all()
            counts = {v.option_index: v.cnt for v in votes}
            for i, opt in enumerate(options):
                opt["votes_count"] = counts.get(i, 0)
            s.query(Post).filter(Post.id == post_id).update({"poll_data": {**post.poll_data, "options": options}}, synchronize_session=False)
            s.commit()
            s.expire_all()
    return {"ok": True}


@posts_router.post("/posts/{post_id}/refresh-poll")
def api_refresh_poll(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        if not post.ap_id:
            raise HTTPException(status_code=400, detail="Local poll has nothing to refresh")
    # Fetch remote object with HTTP Signature
    remote_data = _ap_fetch(post.ap_id, user)
    if not remote_data:
        raise HTTPException(status_code=502, detail="Failed to fetch remote poll")
    obj = remote_data.get("object", remote_data) if isinstance(remote_data, dict) else {}
    if not isinstance(obj, dict):
        raise HTTPException(status_code=502, detail="Invalid remote response")

    # Extract poll data
    one_of = obj.get("oneOf") or obj.get("anyOf") or []
    if not isinstance(one_of, list) or not one_of:
        raise HTTPException(status_code=502, detail="Remote object has no poll data")

    new_options = []
    for opt in one_of:
        if isinstance(opt, dict) and opt.get("name"):
            replies = opt.get("replies", {})
            votes_count = 0
            if isinstance(replies, dict):
                votes_count = replies.get("totalItems", 0)
            new_options.append({"text": opt["name"], "votes_count": votes_count})

    if not new_options:
        raise HTTPException(status_code=502, detail="No valid poll options found")

    # Merge: match by text, take MAX of local and remote counts (never decrease)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post not found")
        old_options = post.poll_data.get("options", [])
        text_to_old = {o.get("text", ""): o for o in old_options}
        for new_opt in new_options:
            old = text_to_old.get(new_opt["text"])
            if old:
                new_opt["votes_count"] = max(new_opt.get("votes_count", 0), old.get("votes_count", 0))

        new_expires = obj.get("endTime") or post.poll_data.get("expires_at", "")
        post.poll_data = {
            "options": new_options,
            "expires_at": new_expires,
        }
        s.commit()
        s.expire_all()

        post = s.query(Post).filter_by(id=post_id).first()
        updated = _post_json(post, s, user)

    return {"ok": True, "post": updated}


@posts_router.post("/pin/post/{post_id}")
def api_pin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post or post.author_id != user.id:
            raise HTTPException(status_code=404, detail="Post not found")
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            return {"ok": True}
        if len(pinned) >= 5:
            raise HTTPException(status_code=400, detail="최대 5개까지 고정할 수 있습니다.")
        pinned.append(post_id)
        s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
        s.commit()
    return {"ok": True}


@posts_router.post("/unpin/post/{post_id}")
def api_unpin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            pinned.remove(post_id)
            s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
            s.commit()
    return {"ok": True}


@posts_router.get("/by-series-number/{username}/{number}")
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


@posts_router.post("/fetch-series")
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


@posts_router.post("/fetch-episode")
def api_fetch_episode(request: Request, url: str = Form(...)):
    user = get_current_user(request)
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


@posts_router.get("/by-number/{username}/{number}")
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
            if post.visibility not in ("public", "unlisted", "home"):
                raise HTTPException(status_code=403, detail="Not authorized")
            return JSONResponse(content=to_ap_note(post), media_type="application/activity+json")
        # 일반 요청 → 로그인 필요
        user = get_current_user(request)
        if not user:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        return _post_json(post, s, user)


@posts_router.post("/fetch-post")
def api_fetch_post(request: Request, url: str = Form(...)):
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    err = _check_fetch_domain_allowed(url)
    if err:
        raise HTTPException(status_code=403, detail=err)

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
    # Include emoji data so frontend can render immediately
    with get_session() as es:
        result["_emojis"] = [
            {"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]}
            for e in _load_emojis(es)
        ]
    return result


__all__ = ["posts_router"]
