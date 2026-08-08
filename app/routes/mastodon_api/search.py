"""Mastodon search endpoints (/api/v1/search, /api/v2/search)."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session as SASession

from app.models import User, Post, Tag
from app.db.database import get_db
from app.config.settings import BASE_URL
from app.routes.mastodon_api._common import (
    _account_json,
    _build_account_counts_map,
    _build_status_maps,
    _maybe_bearer,
    _status_json,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v2/search
# ---------------------------------------------------------------------------
@router.get("/v1/search")
def search_v2(
    request: Request,
    db: SASession = Depends(get_db),
    q: str = "",
    type: str = "",
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    account_id: str | None = None,
    following: bool = False,
):
    viewer = _maybe_bearer(request, db)

    result = {"accounts": [], "statuses": [], "hashtags": []}

    if not q:
        return result

    query_lower = q.lower().strip()

    if not type or type == "accounts":
        users = db.query(User).filter(
            User.is_suspended == False,
            or_(
                User.username.ilike(f"%{query_lower}%"),
                User.display_name.ilike(f"%{query_lower}%"),
            )
        ).limit(limit).all()
        counts = _build_account_counts_map({u.id for u in users}, db)
        result["accounts"] = [_account_json(u, db, viewer, _counts=counts.get(u.id)) for u in users]

    if not type or type == "statuses":
        posts = db.query(Post).filter(
            Post.is_deleted == False,
            Post.visibility.in_(["public", "home"]),
            Post.content.ilike(f"%{query_lower}%"),
        ).order_by(Post.id.desc()).limit(limit).all()
        maps = _build_status_maps(posts, db, viewer)
        result["statuses"] = [s for p in posts if (s := _status_json(p, db, viewer, **maps))]

    if not type or type == "hashtags":
        tag_query = query_lower.lstrip("#")
        tags = db.query(Tag).filter(
            Tag.name.ilike(f"%{tag_query}%")
        ).limit(limit).all()
        result["hashtags"] = [
            {"name": t.display_name or t.name, "url": f"{BASE_URL}/tags/{t.display_name or t.name}"}
            for t in tags
        ]

    return result


# ---------------------------------------------------------------------------
# GET /api/v2/search
# ---------------------------------------------------------------------------
@router.get("/v2/search")
def v2_search(request: Request, db: SASession = Depends(get_db), q: str = "", type: str = "", limit: int = 20, offset: int = 0, resolve: bool = False):
    return search_v2(request, db, q=q, type=type, limit=min(limit, 80), offset=offset)
