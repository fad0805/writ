"""Timeline/feed endpoints extracted from _posts.py."""
import re
import json
import logging
import threading
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import desc, or_, and_, func
from sqlalchemy.orm import selectinload, Session

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark
from app.utils.to_ap_serializer import to_ap_create
from app.serializers import _post_json
from app.config.settings import BASE_URL
from app.core.activitypub import broadcast_to_followers, _post_to_inbox, _federation_allowed, _resolve_actor
from app.core.timeline_stream import broadcast_post, add_post_stream, remove_post_stream, add_stream, remove_stream
from app.db.database import get_session, get_db
from app.routes.auth import get_current_user
from app.utils.emoji import _load_emojis
from app.utils.filter import _timeline_filter



logger = logging.getLogger("writ.api.feed")

feed_router = APIRouter()

TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


def _get_feed(user, tl_type, session, limit=10, offset=0):
    from app.routes.api._interactions import _json_array_has_user
    print(f"[feed] _get_feed uid={user.id if user else None} tl={tl_type} limit={limit} offset={offset}", flush=True)
    _base_opts = [selectinload(Post.author), selectinload(Post.parent)]
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
        _local_user_ids = [row[0] for row in session.query(User.id).filter_by(is_remote=False).all()]
        boosted_ids = list({row[0] for row in session.query(Boost.post_id).join(Post, Boost.post_id == Post.id).filter(
            Boost.user_id.in_(_local_user_ids),
            Post.visibility == "public",
            Post.is_deleted == False
        ).all()})
        _all_boosted_ids = set(boosted_ids)

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
    post_ids = [p.id for p in posts]
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
        _reactions_map = {}
        _default_react = "★"
        _reaction_rows = session.query(
            Like.post_id, func.coalesce(Like.reaction, _default_react), func.count(Like.id)
        ).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all()
        for pid, react, cnt in _reaction_rows:
            if pid not in _reactions_map:
                _reactions_map[pid] = {}
            _reactions_map[pid][react] = cnt
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
    try:
        broadcast_post(post_json, author_id, visibility, is_dm)
    except Exception as e:
        logger.error("Failed to broadcast timeline: %s", e, exc_info=True)


@feed_router.get("/posts/{post_id}/stream")
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


@feed_router.get("/timeline/{tl_type}")
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
