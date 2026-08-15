"""Search and explore endpoints extracted from _core.py."""
import contextlib
from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.threads import spawn
from app.db.database import get_session
from app.db.mention_resolver import _federation_allowed, _resolve_remote_user
from app.models import Bookmark, Boost, Follow, Like, Novel, Post, SeriesFollow, Tag, User
from app.routes.api._novels import _apply_latest_activity_order, _load_novel_meta, _novel_json
from app.serializers import _post_json, _user_json
from app.utils.filter import _timeline_filter

search_router = APIRouter()


@search_router.get("/search/series")
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


@search_router.get("/search/tags")
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


@search_router.get("/explore")
def api_explore(request: Request, limit: int = Query(20, le=100), offset: int = Query(0)):
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
        _reactions_map: dict = {}
        _mentioned_users_map = {}
        _boost_originals = {}
        if post_ids:
            boost_pointer_ids = {p.boost_of_id for p in posts if p.boost_of_id}
            if boost_pointer_ids:
                for orig in s.query(Post).options(selectinload(Post.author)).filter(Post.id.in_(boost_pointer_ids), Post.is_deleted == False).all():
                    _boost_originals[orig.id] = orig
        if user and post_ids:
            _liked_ids = {like.post_id for like in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(post_ids)).all()}
            _boosted_ids = {boost.post_id for boost in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(post_ids)).all()}
            for like in s.query(Like.post_id, Like.reaction).filter(Like.user_id == user.id, Like.post_id.in_(post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[like.post_id] = like.reaction
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
                _followers_map = dict(
                    s.query(SeriesFollow.novel_id, func.count(SeriesFollow.id))
                    .filter(SeriesFollow.novel_id.in_(novel_ids))
                    .group_by(SeriesFollow.novel_id)
                    .all()
                )
            _novel_meta = _load_novel_meta(s, novels)

        return {
            "posts": [_post_json(p, s, user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids, _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map, _mentioned_users_map=_mentioned_users_map, _boost_originals=_boost_originals, _skip_emojis=True) for p in posts],
            "has_more": has_more,
            "novels": [_novel_json(n, s, _followers_map=_followers_map, _episode_meta=_novel_meta) for n in novels],
        }


@search_router.get("/search")
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

        posts = _timeline_filter(posts, s, user, "federated", following_ids)[:20] if user else posts[:20]

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
        if domain and not _federation_allowed(domain, s):
            blocked_domain = domain

        # If query is handle@domain and no remote match yet, try to resolve
        if handle and domain and not blocked_domain:
            already_found = any(
                u.is_remote and u.username.lower().startswith(f"{handle}@") and u.username.lower().endswith(f"@{domain}")
                for u in all_users
            )

            if not already_found:
                with contextlib.suppress(Exception):
                    spawn(_resolve_remote_user, query)

        post_ids = {p.id for p in posts}
        for _p in posts:
            if _p.boost_of_id:
                post_ids.add(_p.boost_of_id)
        _liked_ids = _boosted_ids = _bookmarked_ids = set()
        _my_reaction_map = {}
        _reactions_map: dict = {}
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
            _liked_ids = {like.post_id for like in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(post_ids)).all()}
            _boosted_ids = {boost.post_id for boost in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(post_ids)).all()}
            for like in s.query(Like.post_id, Like.reaction).filter(Like.user_id == user.id, Like.post_id.in_(post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[like.post_id] = like.reaction
            for pid, react, cnt in s.query(Like.post_id, func.coalesce(Like.reaction, "★"), func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all():
                if pid not in _reactions_map:
                    _reactions_map[pid] = {}
                _reactions_map[pid][react] = cnt

        _novel_meta = _load_novel_meta(s, novels)

        result: dict = {
            "posts": [_post_json(p, s, user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids, _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map, _mentioned_users_map=_mentioned_users_map, _boost_originals=_boost_originals) for p in posts],
            "novels": [_novel_json(n, s, _episode_meta=_novel_meta) for n in novels],
            "users": [_user_json(u) for u in all_users],
        }
        if blocked_domain:
            result["blocked_domain"] = blocked_domain
        return result
