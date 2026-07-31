"""Feed/timeline query and federation broadcast logic."""
import re
import logging
import httpx
from typing import List
from urllib.parse import urlparse

from sqlalchemy import desc, except_, or_, and_, func
from sqlalchemy.orm import selectinload, Session, Load

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark
from app.utils.to_ap_serializer import to_ap_create
from app.serializers import _post_json
from app.core.activitypub import broadcast_to_followers, _post_to_inbox, _federation_allowed, _resolve_actor
from app.db.database import get_session
from app.utils.emoji import _load_emojis
from app.utils.filter import _load_user_filters, _timeline_filter

logger = logging.getLogger(__name__)


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
    if tl_type == 'home' and _following_ids:
        _visible_user_ids.update(_following_ids)
    elif tl_type == 'social':
        if _following_ids:
            _visible_user_ids.update(_following_ids)
    elif tl_type == 'local' and _local_ids:
        _visible_user_ids.update(_local_ids)
        visibility = ['public']
    elif tl_type == 'federated':
        _visible_user_ids = None
        visibility = ['public']

    filter_ctx = _load_user_filters(session, user) if user else None
    fetch_size = limit + 20
    posts = []

    page_offset = offset
    while len(posts) < limit + 1:
        batch = query_feed_posts(
            tl_type,
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
        _vote_map = _my_reaction_map = _reactions_map = _mentioned_users_map = {}

    _timeline_emojis = [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(session)]

    feed_dicts = [_post_json(p, session, user, tl_type,
                             _liked_ids=_liked_ids, _boosted_ids=_boosted_ids,
                             _bookmarked_ids=_bookmarked_ids, _vote_map=_vote_map,
                             _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map,
                             _mentioned_users_map=_mentioned_users_map,
                             _skip_emojis=True)
                 for p in posts]

    # Aggregate boost pointers: group by canonical post ID, merge boosters
    groups: dict[int, dict] = {}
    order: list[int] = []
    for d in feed_dicts:
        if not d:
            continue
        key = d.get("boost_of_id") or d["id"]
        if key not in groups:
            groups[key] = d
            order.append(key)
        else:
            existing = groups[key]
            # Keep the entry with the latest created_at
            if (d.get("created_at") or "") > (existing.get("created_at") or ""):
                groups[key] = d
                existing = d
            # Update order: move to the position of the latest entry
            existing_boosted_by = existing.get("boosted_by") or []
            d_boosted_by = d.get("boosted_by") or []
            seen_ids = {b["id"] for b in existing_boosted_by if b}
            merged = list(existing_boosted_by)
            for b in d_boosted_by:
                if b and b["id"] not in seen_ids:
                    seen_ids.add(b["id"])
                    merged.append(b)
            existing["boosted_by"] = merged

    feed_dicts = [groups[k] for k in order]

    return feed_dicts, has_more, _timeline_emojis


def query_feed_posts(
        tl_type: str,
        visible_user_ids: set,
        local_ids: set,
        user_id: int,
        visibility: list,
        session: Session,
        base_opts: List[Load],
        fetch_size: int,
        offset: int):

    posts = []
    if tl_type != 'social':
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
    else:
        local_public_ids = (local_ids or set()) - (visible_user_ids or set())
        q = session.query(Post).options(*base_opts).filter(
            Post.is_deleted == False,
        )
        conditions = []
        if visible_user_ids:
            conditions.append(
                and_(Post.author_id.in_(visible_user_ids), Post.visibility.in_(visibility))
            )
        if local_public_ids:
            conditions.append(
                and_(Post.author_id.in_(local_public_ids), Post.visibility == 'public')
            )
        if not conditions:
            return []

        allowed_ids = visible_user_ids | local_public_ids
        try:
            q = q.filter(or_(*conditions)).filter(
                or_(
                    Post.parent == None,
                    Post.parent.has(Post.author_id.in_(allowed_ids))
                )
            ).order_by(desc(Post.created_at)).offset(offset).limit(fetch_size)
            posts = q.all()
        except Exception as e:
            logging.error(f'No post in social feed: {e}')

        posts = [
            p for p in posts
            if not (
                p.visibility == "mention" and p.is_dm
                and p.author_id != user_id and local_ids
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
