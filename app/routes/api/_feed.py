"""Timeline/feed endpoints extracted from _posts.py."""
import re
import logging
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from typing import List
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import desc, or_, and_, func
from sqlalchemy.orm import selectinload, Session, Load

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark
from app.utils.to_ap_serializer import to_ap_create
from app.serializers import _post_json
from app.core.activitypub import broadcast_to_followers, _post_to_inbox, _federation_allowed, _resolve_actor
from app.core.timeline_stream import add_post_stream, remove_post_stream
from app.db.database import get_session, get_db
from app.routes.auth import get_current_user
from app.utils.emoji import _load_emojis
from app.utils.filter import _load_user_filters, _timeline_filter

logger = logging.getLogger("writ.api.feed")

feed_router = APIRouter()

TIMELINE_LABELS = {
    "federated": "연합", "local": "로컬", "social": "소셜", "home": "홈",
}


def _get_feed(user, tl_type, session, limit=10, offset=0):
    print(f"[feed] _get_feed uid={user.id if user else None} tl={tl_type} limit={limit} offset={offset}", flush=True)
    _base_opts = [selectinload(Post.author), selectinload(Post.parent)]
    user_id = user.id if user else None

    _following_ids = None
    if user and tl_type in ("home", "social"):
        _following_ids = {
            row[0]
            for row in session.query(Follow.following_id)
            .filter_by(follower_id=user.id, accepted=True)
        }
        _following_ids.add(user.id)

    _local_ids = None
    if tl_type in ("social", "local"):
        _local_ids = {
            row[0]
            for row in session.query(User.id).filter_by(is_remote=False)
        }

    _visible_user_ids = {user.id} if user else set()
    visibility = ['mention', 'followers', 'home', 'public']
    _local_public_ids = None
    if tl_type == 'home' and _following_ids:
        _visible_user_ids.update(_following_ids)
    elif tl_type == 'social':
        if _following_ids:
            _visible_user_ids.update(_following_ids)
        if _local_ids:
            _local_public_ids = _local_ids - _visible_user_ids
            if not _local_public_ids:
                _local_public_ids = None
    elif tl_type == 'local' and _local_ids:
        _visible_user_ids.update(_local_ids)
        visibility = ['public']
    elif tl_type == 'federated':
        _visible_user_ids = None
        visibility = ['public']

    filter_ctx = _load_user_filters(session, user) if user else None
    fetch_size = limit + 20
    posts = []

    if tl_type == 'social' and _local_public_ids:
        batch1 = query_feed_posts(
            _visible_user_ids, _local_ids, user_id, visibility,
            session, _base_opts, fetch_size, offset=0
        )
        batch2 = query_feed_posts(
            _local_public_ids, _local_ids, user_id, ['public'],
            session, _base_opts, fetch_size, offset=0
        )
        combined = sorted(batch1 + batch2, key=lambda p: p.created_at, reverse=True)
        seen = set()
        batch = []
        for p in combined:
            if p.id not in seen:
                seen.add(p.id)
                batch.append(p)
        if user:
            batch = _timeline_filter(batch, session, user, tl_type, _following_ids, filter_ctx=filter_ctx)
        posts = batch[offset:offset + limit + 1]
        has_more = len(posts) > limit
        posts = posts[:limit]

    else:
        page_offset = offset
        while len(posts) < limit + 1:
            batch = query_feed_posts(
                _visible_user_ids, _local_ids, user_id, visibility,
                session, _base_opts, fetch_size, offset=page_offset
            )
            if not batch:
                break
            batch_size = len(batch)
            if user:
                batch = _timeline_filter(batch, session, user, tl_type, _following_ids, filter_ctx=filter_ctx)
            needed = limit + 1 - len(posts)
            posts.extend(batch[:needed])
            if batch_size < fetch_size:
                break
            page_offset += fetch_size

        has_more = len(posts) > limit
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

    _timeline_emojis = [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(session)]

    return [_post_json(p, session, user, tl_type,
                       _liked_ids=_liked_ids, _boosted_ids=_boosted_ids,
                       _bookmarked_ids=_bookmarked_ids, _vote_map=_vote_map,
                       _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map,
                       _booster_map=_booster_map, _mentioned_users_map=_mentioned_users_map,
                       _skip_emojis=True)
            for p in posts], has_more, _timeline_emojis


def query_feed_posts(
        visible_user_ids: set,
        local_ids: set,
        user_id: int,
        visibility: list,
        session: Session,
        base_opts: List[Load],
        fetch_size: int,
        offset: int):

    if visible_user_ids is not None:
        visible_posts = session.query(Post).options(*base_opts).filter(
            Post.is_deleted == False,
            Post.visibility.in_(visibility),
            Post.author_id.in_(visible_user_ids),
            or_(
                Post.parent == None,
                Post.parent.has(Post.author_id.in_(visible_user_ids))
            ),
        ).order_by(desc(Post.created_at)).offset(offset).limit(fetch_size).all()
    else:
        visible_posts = session.query(Post).options(*base_opts).filter(
            Post.is_deleted == False,
            Post.visibility.in_(visibility),
        ).order_by(desc(Post.created_at)).offset(offset).limit(fetch_size).all()

    posts = [
        p for p in visible_posts
        if not (
            p.visibility == "mention"
            and p.is_dm
            and p.author_id != user_id
            and local_ids
            and p.author_id in local_ids
            and user_id not in (p.mentioned_user_ids or [])
        )
    ]

    return posts


def _broadcast_federation(user_id, post_id, visibility, plain_content=''):
    with get_session() as ap_s:
        user = ap_s.query(User).filter_by(id=user_id).first()
        post = ap_s.query(Post).filter_by(id=post_id).first()
        if not user or not post:
            logger.warning(f"Broadcast aborted: user_id={user_id} or post_id={post_id} not found")
            return

        create_activity = to_ap_create(post)

        inboxes = set()
        if visibility == "mention":
            if post.mentioned_user_ids:
                mu_users = ap_s.query(User).filter(
                    User.id.in_(post.mentioned_user_ids), User.is_remote == True
                ).all()
                for mu in mu_users:
                    inbox = mu.inbox_url
                    if inbox:
                        inboxes.add(inbox)
        else:
            if post.in_reply_to_id and post.parent:
                parent_author = post.parent.author
                if parent_author and parent_author.is_remote:
                    inbox = parent_author.inbox_url
                    if inbox:
                        inboxes.add(inbox)
                elif parent_author and not parent_author.is_remote:
                    pf_follows = ap_s.query(Follow).filter(
                        Follow.following_id == parent_author.id,
                        Follow.follower.has(is_remote=True),
                    ).all()
                    for pf in pf_follows:
                        inbox = pf.follower.shared_inbox_url or pf.follower.inbox_url
                        if inbox:
                            inboxes.add(inbox)

            if post.mentioned_user_ids:
                follower_ids = {f.following_id for f in ap_s.query(Follow).filter(
                    Follow.following_id == user.id,
                    Follow.follower.has(is_remote=True),
                ).all()} if post.mentioned_user_ids else set()
                mu_users = ap_s.query(User).filter(
                    User.id.in_(post.mentioned_user_ids), User.is_remote == True
                ).all()
                for mu in mu_users:
                    if mu.id not in follower_ids:
                        inbox = mu.inbox_url
                        if inbox:
                            inboxes.add(inbox)
    for inbox in inboxes:
        _post_to_inbox(inbox, create_activity, user)

    broadcast_to_followers(user, create_activity)

    if visibility != "mention":
        remote_handles = set(re.findall(r'@([a-zA-Z0-9_]+@[\w.-]+\.[a-zA-Z]{2,})', plain_content or ""))
        for handle in remote_handles:
            with get_session() as s:
                remote_user = s.query(User).filter(
                    User.username == handle, User.is_remote == True
                ).first()
            if remote_user:
                inbox = remote_user.inbox_url
                if inbox:
                    _post_to_inbox(inbox, create_activity, user)
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
                    with get_session() as s:
                        remote_user = s.query(User).get(resolved.id)
                    if remote_user:
                        inbox = remote_user.inbox_url
                        if inbox:
                            _post_to_inbox(inbox, create_activity, user)
            except Exception:
                pass


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
