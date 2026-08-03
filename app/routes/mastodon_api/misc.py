"""Miscellaneous Mastodon endpoints (filters, lists, bookmarks, push, trends, etc.)."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session as SASession

from app.models import User, Like, Boost, Bookmark, Tag, CustomEmoji, UserMute, UserBlock
from app.db.database import get_db
from app.config.settings import BASE_URL
from app.utils.emoji import _emoji_url
from app.routes.mastodon_api._common import (
    STAR_REACTION,
    _account_json,
    _build_account_counts_map,
    _build_status_maps,
    _maybe_bearer,
    _require_bearer,
    _status_json,
    _visibility_to_mastodon,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/custom_emojis
# ---------------------------------------------------------------------------
@router.get("/v1/custom_emojis")
def custom_emojis(db: SASession = Depends(get_db)):
    emojis = db.query(CustomEmoji).filter(
        (CustomEmoji.domain == "") | (CustomEmoji.domain.is_(None))
    ).all()
    return [
        {
            "shortcode": e.keyword,
            "url": e.source_url or _emoji_url(e.file_name, e.domain or "", e.category or ""),
            "static_url": e.source_url or _emoji_url(e.file_name, e.domain or "", e.category or ""),
            "visible_in_picker": True,
            "category": e.category or "",
            "aliases": e.aliases or [],
        }
        for e in emojis
    ]
# ---------------------------------------------------------------------------
# GET /api/v1/followed_tags
# ---------------------------------------------------------------------------
@router.get("/v1/followed_tags")
def list_followed_tags(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/filters (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/filters")
def list_filters(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# POST /api/v1/filters (stub)
# ---------------------------------------------------------------------------
@router.post("/v1/filters")
async def create_filter(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    body = await request.json()
    return {
        "id": "1",
        "title": body.get("title", ""),
        "context": body.get("context", []),
        "expires_at": None,
        "filter_action": body.get("filter_action", "warn"),
        "keywords": [],
        "statuses": [],
    }


# ---------------------------------------------------------------------------
# GET /api/v2/filters (stub)
# ---------------------------------------------------------------------------
@router.get("/v2/filters")
def list_filters_v2(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/preferences
# ---------------------------------------------------------------------------
@router.get("/v1/preferences")
def get_preferences(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {
        "posting:default_visibility": _visibility_to_mastodon(user.default_visibility),
        "posting:default_sensitive": False,
        "posting:default_language": "ko",
        "reading:expand_media": "default",
        "reading:expand_spoilers": False,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/follow_requests
# ---------------------------------------------------------------------------
@router.get("/v1/follow_requests")
def list_follow_requests(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=80),
):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/blocks (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/blocks")
def list_blocks(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    rows = db.query(UserBlock).filter(UserBlock.user_id == user.id).order_by(UserBlock.created_at.desc()).all()
    counts = _build_account_counts_map({m.target_user_id for m in rows}, db)
    return [_account_json(m.target_user, db, viewer=user, _counts=counts.get(m.target_user_id)) for m in rows]


# ---------------------------------------------------------------------------
# GET /api/v1/mutes
# ---------------------------------------------------------------------------
@router.get("/v1/mutes")
def list_mutes(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    rows = db.query(UserMute).filter(UserMute.user_id == user.id).order_by(UserMute.created_at.desc()).all()
    counts = _build_account_counts_map({m.target_user_id for m in rows}, db)
    return [_account_json(m.target_user, db, viewer=user, _counts=counts.get(m.target_user_id)) for m in rows]


# ---------------------------------------------------------------------------
# GET /api/v1/bookmarks
# ---------------------------------------------------------------------------
@router.get("/v1/bookmarks")
def list_bookmarks(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=80),
):
    user = _require_bearer(request, db)
    q = db.query(Bookmark).filter(Bookmark.user_id == user.id)

    if max_id:
        q = q.filter(Bookmark.id < int(max_id))
    if since_id:
        q = q.filter(Bookmark.id > int(since_id))
    if min_id:
        q = q.filter(Bookmark.id > int(min_id))

    bookmarks = q.order_by(Bookmark.id.desc()).limit(limit).all()

    _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
        Like.user_id == user.id,
        or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
        Like.post_id.in_([b.post_id for b in bookmarks])
    ).all()) if bookmarks else set()
    _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
        Boost.user_id == user.id,
        Boost.post_id.in_([b.post_id for b in bookmarks])
    ).all()) if bookmarks else set()

    maps = _build_status_maps([bm.post for bm in bookmarks if bm.post], db, user)
    result = []
    for bm in bookmarks:
        if bm.post and not bm.post.is_deleted:
            s = _status_json(bm.post, db, viewer=user, _liked_ids=_liked_ids,
                             _boosted_ids=_boosted_ids, _bookmarked_ids={bm.post_id}, **maps)
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/favourites
# ---------------------------------------------------------------------------
@router.get("/v1/favourites")
def list_favourites(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=80),
):
    user = _require_bearer(request, db)
    q = db.query(Like).filter(
        Like.user_id == user.id,
        or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
    )

    if max_id:
        q = q.filter(Like.id < int(max_id))
    if since_id:
        q = q.filter(Like.id > int(since_id))
    if min_id:
        q = q.filter(Like.id > int(min_id))

    likes = q.order_by(Like.id.desc()).limit(limit).all()

    _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
        Boost.user_id == user.id,
        Boost.post_id.in_([l.post_id for l in likes])
    ).all()) if likes else set()

    maps = _build_status_maps([l.post for l in likes if l.post], db, user)
    result = []
    for like in likes:
        if like.post and not like.post.is_deleted:
            s = _status_json(like.post, db, viewer=user, _liked_ids={like.post_id},
                             _boosted_ids=_boosted_ids, **maps)
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/lists (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/lists")
def list_lists(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/suggestions (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/suggestions")
def list_suggestions(
    request: Request,
    db: SASession = Depends(get_db),
    limit: int = Query(default=40, le=80),
):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/tags
# ---------------------------------------------------------------------------
@router.get("/v1/tags")
def list_tags(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/featured_tags (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/featured_tags")
def featured_tags(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/domain_blocks (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/domain_blocks")
def domain_blocks(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/endorsements (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/endorsements")
def endorsements(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/markers (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/markers")
def get_markers(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# POST /api/v1/markers (stub)
# ---------------------------------------------------------------------------
@router.post("/v1/markers")
async def save_markers(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# POST /api/v1/push/subscription (stub)
# ---------------------------------------------------------------------------
@router.post("/v1/push/subscription")
async def create_push_subscription(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    body = await request.json()
    return {
        "id": "1",
        "endpoint": body.get("data", {}).get("endpoint", ""),
        "alerts": body.get("data", {}).get("alerts", {}),
        "policy": "all",
    }


# ---------------------------------------------------------------------------
# GET /api/v1/push/subscription (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/push/subscription")
def get_push_subscription(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# DELETE /api/v1/push/subscription (stub)
# ---------------------------------------------------------------------------
@router.delete("/v1/push/subscription")
def delete_push_subscription(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# PUT /api/v1/push/subscription (stub)
# ---------------------------------------------------------------------------
@router.put("/v1/push/subscription")
async def update_push_subscription(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# GET /api/v1/announcements (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/announcements")
def list_announcements(request: Request, db: SASession = Depends(get_db)):
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/trends (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/trends")
def get_trends(db: SASession = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.id.desc()).limit(10).all()
    return [
        {"name": t.display_name or t.name, "url": f"{BASE_URL}/explore?q=%23{t.display_name or t.name}", "history": []}
        for t in tags
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/trends/tags (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/trends/tags")
def get_trending_tags(db: SASession = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.id.desc()).limit(10).all()
    return [
        {"name": t.display_name or t.name, "url": f"{BASE_URL}/explore?q=%23{t.display_name or t.name}", "history": []}
        for t in tags
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/trends/statuses (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/trends/statuses")
def get_trending_statuses(
    request: Request,
    db: SASession = Depends(get_db),
    limit: int = Query(default=20, le=80),
):
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/directory
# ---------------------------------------------------------------------------
@router.get("/v1/directory")
def get_directory(
    request: Request,
    db: SASession = Depends(get_db),
    limit: int = Query(default=40, le=80),
    order: str = "active",
    local: bool = False,
):
    viewer = _maybe_bearer(request, db)
    q = db.query(User).filter(User.is_remote == False, User.is_suspended == False)
    if local:
        q = q.filter(User.is_remote == False)
    users = q.order_by(User.updated_at.desc()).limit(limit).all()
    counts = _build_account_counts_map({u.id for u in users}, db)
    return [_account_json(u, db, viewer, _counts=counts.get(u.id)) for u in users]


# ---------------------------------------------------------------------------
# GET /api/v1/conversations (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/conversations")
def list_conversations(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=20, le=80),
):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/scheduled_statuses (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/scheduled_statuses")
def list_scheduled(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []
