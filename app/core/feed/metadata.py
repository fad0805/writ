"""Post metadata loading — likes, boosts, bookmarks, votes, reactions, mentions, emojis."""
import copy
from typing import TypedDict
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models import User, Post, Like, Boost, Vote, Bookmark
from app.utils.emoji import _load_emojis


class PostMetadata(TypedDict):
    liked_ids: set[int]
    my_reaction_map: dict[int, str]
    boosted_ids: set[int]
    bookmarked_ids: set[int]
    vote_map: dict[int, int]
    reactions_map: dict[int, dict[str, int]]
    mentioned_users_map: dict[int, list[str]]
    counts_map: dict[int, dict[str, int]]


_EMPTY_POST_METADATA: PostMetadata = {
    "liked_ids": set(),
    "my_reaction_map": {},
    "boosted_ids": set(),
    "bookmarked_ids": set(),
    "vote_map": {},
    "reactions_map": {},
    "mentioned_users_map": {},
    "counts_map": {},
}


def _load_boost_originals(session, posts):
    """3. 부스트된 원본 포스트들을 일괄 조회"""
    _boost_originals = {}
    _boost_pointer_ids = {p.boost_of_id for p in posts if p.boost_of_id}
    if _boost_pointer_ids:
        for _orig in session.query(Post).options(selectinload(Post.author)).filter(Post.id.in_(_boost_pointer_ids), Post.is_deleted == False).all():
            _boost_originals[_orig.id] = _orig
    return _boost_originals


def _feed_used_emojis(session, posts, boost_originals=None):
    """Return only the custom emojis actually referenced by the feed posts."""
    all_emojis = _load_emojis(session)
    if not all_emojis or not posts:
        return []
    texts = []
    for p in posts:
        texts.append(p.content or "")
        texts.append(p.summary or "")
        if p.author:
            texts.append(p.author.display_name or "")
        parent = getattr(p, "parent", None)
        if parent is not None and not parent.is_deleted:
            texts.append(parent.content or "")
            texts.append(parent.summary or "")
            if parent.author:
                texts.append(parent.author.display_name or "")
        if p.boost_of_id:
            orig = (boost_originals or {}).get(p.boost_of_id)
            if orig is None:
                try:
                    orig = session.query(Post).filter_by(id=p.boost_of_id).first()
                except Exception:
                    orig = None
            if orig is not None and not orig.is_deleted:
                texts.append(orig.content or "")
                texts.append(orig.summary or "")
                if orig.author:
                    texts.append(orig.author.display_name or "")
    # 리액션(커스텀 이모지)에만 쓰인 이모지도 렌더링되도록 반응 키워드 포함
    _post_ids = {p.id for p in posts} | {p.boost_of_id for p in posts if p.boost_of_id}
    if _post_ids:
        for (r,) in session.query(Like.reaction).filter(
            Like.post_id.in_(_post_ids), Like.reaction.isnot(None)
        ).all():
            texts.append(r or "")
    needle = " ".join(texts).lower()
    used = []
    seen = set()
    for e in all_emojis:
        kw = e["keyword"]
        if kw in seen:
            continue
        seen.add(kw)
        if f":{kw.lower()}:" in needle:
            used.append({"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]})
    return used


def _load_post_metadata(
        session: Session, user: User, posts: list[Post]) -> PostMetadata:
    if not posts or user is None:
        return copy.deepcopy(_EMPTY_POST_METADATA)

    post_ids = {p.id for p in posts}
    post_ids.update(
        p.boost_of_id
        for p in posts
        if p.boost_of_id
    )

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

    _reactions_map: dict[int, dict[str, int]] = {}
    _default_react = "★"

    # 좋아요/부스트/답글 카운트 배치 집계 (lazy="selectin" 컬렉션 로드 대체)
    counts_map: dict[int, dict[str, int]] = {}
    for pid, cnt in session.query(Like.post_id, func.count(Like.id)).filter(
        Like.post_id.in_(post_ids)
    ).group_by(Like.post_id).all():
        counts_map.setdefault(pid, {})["likes"] = cnt
    for pid, cnt in session.query(Boost.post_id, func.count(Boost.id)).filter(
        Boost.post_id.in_(post_ids)
    ).group_by(Boost.post_id).all():
        counts_map.setdefault(pid, {})["boosts"] = cnt
    # replies_count 프로퍼티와 동일 조건: in_reply_to_id 기준 + 삭제 제외
    for pid, cnt in session.query(Post.in_reply_to_id, func.count(Post.id)).filter(
        Post.in_reply_to_id.in_(post_ids), Post.is_deleted == False
    ).group_by(Post.in_reply_to_id).all():
        counts_map.setdefault(pid, {})["replies"] = cnt

    reaction_expr = func.coalesce(Like.reaction, _default_react)
    _reaction_rows = (
        session.query(
            Like.post_id,
            reaction_expr,
            func.count(Like.id)
        )
        .filter(Like.post_id.in_(post_ids))
        .group_by(Like.post_id, reaction_expr)
        .order_by(Like.post_id, func.min(Like.id)).all()
    )
    for pid, react, cnt in _reaction_rows:
        _reactions_map.setdefault(pid, {})[react] = cnt

    all_mentioned_ids = {
        uid
        for p in posts
        for uid in (p.mentioned_user_ids or [])
    }

    _mentioned_users_map: dict[int, list[str]] = {}
    if all_mentioned_ids:
        users = session.query(User).filter(User.id.in_(all_mentioned_ids)).all()
        _mentioned_users = {
            u.id: (
                f"{u.username.split('@')[0]}@{urlparse(u.remote_url).hostname}"
                if u.is_remote and u.remote_url
                else u.username
            )
            for u in users
        }
        for p in posts:
            _mentioned_users_map[p.id] = [
                _mentioned_users[mid]
                for mid in (p.mentioned_user_ids or [])
                if mid in _mentioned_users
            ]

    return {
        "liked_ids": _liked_ids,
        "my_reaction_map": _my_reaction_map,
        "boosted_ids": _boosted_ids,
        "bookmarked_ids": _bookmarked_ids,
        "vote_map": _vote_map,
        "reactions_map": _reactions_map,
        "mentioned_users_map": _mentioned_users_map,
        "counts_map": counts_map,
    }
