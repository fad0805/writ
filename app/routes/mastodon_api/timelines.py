"""Mastodon timeline endpoints (/api/v1/timelines*, /api/v1/tags*)."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session as SASession

from app.models import User, Post, Follow, Like, Boost, Bookmark, Tag
from app.db.database import get_db
from app.config.settings import BASE_URL
from app.utils.filter import _load_user_filters, _timeline_filter
from app.routes.mastodon_api._common import (
    MastodonAPIError,
    STAR_REACTION,
    _boost_status_json,
    _build_status_maps,
    _maybe_bearer,
    _require_bearer,
    _status_json,
)

router = APIRouter()


def _load_posts_by_id(db: SASession, ids) -> dict:
    """배치로 id 목록의 Post를 로드해 루프 내 개별 쿼리(N+1)를 제거한다."""
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    return {p.id: p for p in db.query(Post).filter(Post.id.in_(ids)).all()}


# ---------------------------------------------------------------------------
# GET /api/v1/timelines/home
# ---------------------------------------------------------------------------
@router.get("/v1/timelines/home")
def home_timeline(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=100),
):
    user = _require_bearer(request, db)

    following_ids = [f.following_id for f in db.query(Follow.following_id).filter(
        Follow.follower_id == user.id, Follow.accepted == True
    ).all()]
    following_ids.append(user.id)

    q = db.query(Post).filter(
        Post.author_id.in_(following_ids),
        Post.is_deleted == False,
        Post.visibility.in_(["public", "home", "followers"]),
    )

    if max_id:
        q = q.filter(Post.id < int(max_id))
    if since_id:
        q = q.filter(Post.id > int(since_id))
    if min_id:
        q = q.filter(Post.id > int(min_id))

    posts = q.order_by(Post.id.desc()).limit(limit).all()

    filter_ctx = _load_user_filters(db, user)
    posts = _timeline_filter(posts, db, user, "home", following_ids, filter_ctx)

    _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
        Like.user_id == user.id,
        or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
        Like.post_id.in_([p.id for p in posts])
    ).all()) if posts else set()
    _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
        Boost.user_id == user.id, Boost.post_id.in_([p.id for p in posts])
    ).all()) if posts else set()
    _bookmarked_ids = set(r[0] for r in db.query(Bookmark.post_id).filter(
        Bookmark.user_id == user.id, Bookmark.post_id.in_([p.id for p in posts])
    ).all()) if posts else set()

    following_set = set(following_ids)

    _original_map = _load_posts_by_id(db, [p.boost_of_id for p in posts])
    _parent_map = _load_posts_by_id(db, [p.in_reply_to_id for p in posts])

    maps = _build_status_maps(posts, db, user)
    result = []
    for p in posts:
        if p.boost_of_id:
            original = _original_map.get(p.boost_of_id)
            if original and not original.is_deleted:
                # Reply filtering for boosted replies
                if original.in_reply_to_id and original.author_id != user.id:
                    parent = _parent_map.get(original.in_reply_to_id)
                    if parent and parent.author_id not in following_set and parent.author_id != user.id:
                        continue
                s = _boost_status_json(p, original, db, viewer=user,
                                       _boosted_ids=_boosted_ids, _liked_ids=_liked_ids,
                                       _bookmarked_ids=_bookmarked_ids, **maps)
                if s:
                    result.append(s)
        else:
            # Reply filtering: drop replies to posts by non-followed, non-self users (but always keep own posts)
            if p.in_reply_to_id and p.author_id != user.id:
                parent = _parent_map.get(p.in_reply_to_id)
                if parent and parent.author_id not in following_set and parent.author_id != user.id:
                    continue
            s = _status_json(p, db, viewer=user, _boosted_ids=_boosted_ids,
                             _liked_ids=_liked_ids, _bookmarked_ids=_bookmarked_ids, **maps)
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/timelines/public
# ---------------------------------------------------------------------------
@router.get("/v1/timelines/public")
def public_timeline(
    request: Request,
    db: SASession = Depends(get_db),
    local: bool = False,
    remote: bool = False,
    only_media: bool = False,
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=100),
):
    viewer = _maybe_bearer(request, db)

    q = db.query(Post).filter(
        Post.visibility == "public",
        Post.is_deleted == False,
        Post.boost_of_id.is_(None),
    )

    if local:
        q = q.join(Post.author).filter(User.is_remote == False)
    if remote:
        q = q.join(Post.author).filter(User.is_remote == True)
    if only_media:
        q = q.filter(
            Post.media_attachments != None,
            cast(Post.media_attachments, String) != "[]",
            cast(Post.media_attachments, String) != "null",
        )

    if max_id:
        q = q.filter(Post.id < int(max_id))
    if since_id:
        q = q.filter(Post.id > int(since_id))
    if min_id:
        q = q.filter(Post.id > int(min_id))

    posts = q.order_by(Post.id.desc()).limit(limit).all()

    if viewer:
        filter_ctx = _load_user_filters(db, viewer)
        posts = _timeline_filter(posts, db, viewer, "local" if local else "federated", [], filter_ctx)

    _liked_ids = set()
    _boosted_ids = set()
    _bookmarked_ids = set()
    if viewer:
        post_ids = [p.id for p in posts]
        _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
            Like.user_id == viewer.id,
            or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
            Like.post_id.in_(post_ids)
        ).all()) if post_ids else set()
        _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
            Boost.user_id == viewer.id, Boost.post_id.in_(post_ids)
        ).all()) if post_ids else set()
        _bookmarked_ids = set(r[0] for r in db.query(Bookmark.post_id).filter(
            Bookmark.user_id == viewer.id, Bookmark.post_id.in_(post_ids)
        ).all()) if post_ids else set()

    _original_map = _load_posts_by_id(db, [p.boost_of_id for p in posts])

    maps = _build_status_maps(posts, db, viewer)
    result = []
    for p in posts:
        if p.boost_of_id:
            original = _original_map.get(p.boost_of_id)
            if original and not original.is_deleted:
                s = _boost_status_json(p, original, db, viewer=viewer,
                                       _boosted_ids=_boosted_ids, _liked_ids=_liked_ids,
                                       _bookmarked_ids=_bookmarked_ids, **maps)
                if s:
                    result.append(s)
        else:
            s = _status_json(p, db, viewer=viewer, _boosted_ids=_boosted_ids,
                             _liked_ids=_liked_ids, _bookmarked_ids=_bookmarked_ids, **maps)
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/timelines/tag/:tag
# ---------------------------------------------------------------------------
@router.get("/v1/timelines/tag/{tag}")
def hashtag_timeline(
    tag: str,
    request: Request,
    db: SASession = Depends(get_db),
    local: bool = False,
    remote: bool = False,
    only_media: bool = False,
    any_: list[str] = Query(default=[], alias="any"),
    all_: list[str] = Query(default=[], alias="all"),
    none_: list[str] = Query(default=[], alias="none"),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=100),
):
    viewer = _maybe_bearer(request, db)
    tag_obj = db.query(Tag).filter(Tag.name == tag.lower()).first()
    if not tag_obj:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    q = db.query(Post).filter(
        Post.tag_list.any(Tag.id == tag_obj.id),
        Post.visibility.in_(["public", "home"]),
        Post.is_deleted == False,
        Post.boost_of_id.is_(None),
    )

    if local:
        q = q.join(Post.author).filter(User.is_remote == False)
    if remote:
        q = q.join(Post.author).filter(User.is_remote == True)

    if max_id:
        q = q.filter(Post.id < int(max_id))
    if since_id:
        q = q.filter(Post.id > int(since_id))
    if min_id:
        q = q.filter(Post.id > int(min_id))

    posts = q.order_by(Post.id.desc()).limit(limit).all()

    if viewer:
        filter_ctx = _load_user_filters(db, viewer)
        posts = _timeline_filter(posts, db, viewer, "federated", [], filter_ctx)

    _liked_ids = set()
    _boosted_ids = set()
    _bookmarked_ids = set()
    if viewer:
        post_ids = [p.id for p in posts]
        if post_ids:
            _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
                Like.user_id == viewer.id,
                or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
                Like.post_id.in_(post_ids)
            ).all())
            _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
                Boost.user_id == viewer.id, Boost.post_id.in_(post_ids)
            ).all())
            _bookmarked_ids = set(r[0] for r in db.query(Bookmark.post_id).filter(
                Bookmark.user_id == viewer.id, Bookmark.post_id.in_(post_ids)
            ).all())

    maps = _build_status_maps(posts, db, viewer)
    result = []
    for p in posts:
        s = _status_json(p, db, viewer=viewer, _boosted_ids=_boosted_ids,
                         _liked_ids=_liked_ids, _bookmarked_ids=_bookmarked_ids, **maps)
        if s:
            result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/tags/:tag
# ---------------------------------------------------------------------------
@router.get("/v1/tags/{tag}")
def get_tag(tag: str, request: Request, db: SASession = Depends(get_db)):
    viewer = _maybe_bearer(request, db)
    tag_obj = db.query(Tag).filter(Tag.name == tag.lower()).first()
    if not tag_obj:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    name = tag_obj.display_name or tag_obj.name
    return {
        "name": name,
        "url": f"{BASE_URL}/tags/{name}",
        "following": False,
        "history": [],
    }
