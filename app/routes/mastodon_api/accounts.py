"""Mastodon account endpoints (/api/v1/accounts*)."""
import html
import re

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import String, cast
from sqlalchemy.orm import Session as SASession

from app.models import User, Post, Follow, now
from app.db.database import get_db
from app.core.relationship import follow_user, unfollow_user, mute_user, unmute_user, block_user, unblock_user
from app.routes.mastodon_api._common import (
    MastodonAPIError,
    _account_json,
    _boost_status_json,
    _build_account_counts_map,
    _build_status_maps,
    _maybe_bearer,
    _query_id_list,
    _relationship_json,
    _require_bearer,
    _status_json,
    _visibility_from_mastodon,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/lookup?acct=user@domain
# ---------------------------------------------------------------------------
@router.get("/v1/accounts/lookup")
def lookup_account(acct: str = "", request: Request = None, db: SASession = Depends(get_db)):
    if not acct:
        raise MastodonAPIError(status_code=400, detail="Missing acct parameter")
    raw = acct.strip().lstrip("/@")
    local_part = raw.split("@")[0].strip() if "@" in raw else raw.strip()
    full_acct = raw.strip()
    user = db.query(User).filter(
        User.is_suspended == False,
        ((User.username == full_acct) | (User.username == local_part) | (User.display_handle == full_acct) | (User.display_handle == local_part))
    ).first()
    if not user:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    viewer = _maybe_bearer(request, db) if request is not None else None
    return _account_json(user, db, viewer=viewer)


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/verify_credentials
# ---------------------------------------------------------------------------
@router.get("/v1/accounts/verify_credentials")
def verify_account_credentials(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return _account_json(user, db, viewer=user)


# ---------------------------------------------------------------------------
# PATCH /api/v1/accounts/update_credentials
# ---------------------------------------------------------------------------
@router.patch("/v1/accounts/update_credentials")
async def update_credentials(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    ct = request.headers.get("content-type", "")
    if "multipart" in ct:
        form = await request.form()
        display_name = form.get("display_name")
        note = form.get("note")
        avatar = form.get("avatar")
        header = form.get("header")
        locked = form.get("locked")
        bot = form.get("bot")
        source_privacy = form.get("source[privacy]")
        fields_attributes = form.get("fields_attributes")
    else:
        body = await request.json()
        display_name = body.get("display_name")
        note = body.get("note")
        locked = body.get("locked")
        bot = body.get("bot")
        avatar = None
        header = None
        source_privacy = body.get("source", {}).get("privacy") if isinstance(body.get("source"), dict) else None
        fields_attributes = body.get("fields_attributes")

    if display_name is not None:
        user.display_name = str(display_name)[:128]
    if note is not None:
        user.summary = html.unescape(re.sub(r"<[^>]+>", "", str(note)))[:500]
    if locked is not None:
        user.is_locked = bool(locked)
    if bot is not None:
        user.is_bot = bool(bot)
    if source_privacy:
        user.default_visibility = _visibility_from_mastodon(source_privacy)
    if fields_attributes and isinstance(fields_attributes, dict):
        fields = []
        for key in sorted(fields_attributes.keys()):
            val = fields_attributes[key]
            if val is None:
                continue
            name = val.get("name", "") if isinstance(val, dict) else ""
            value = val.get("value", "") if isinstance(val, dict) else ""
            if name:
                fields.append({"name": name, "value": value, "verified_at": None})
        user.custom_fields = fields

    user.updated_at = now()
    db.commit()
    db.refresh(user)
    return _account_json(user, db, viewer=user)


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/relationships
# ---------------------------------------------------------------------------
@router.get("/v1/accounts/relationships")
def get_relationships(
    request: Request,
    db: SASession = Depends(get_db),
    id: list[str] = Query(default=[]),
):
    user = _require_bearer(request, db)
    ids = id or _query_id_list(request)
    result = []
    for uid in ids:
        try:
            uid_int = int(uid)
        except ValueError:
            continue
        target = db.query(User).filter_by(id=uid_int).first()
        if not target:
            continue
        result.append(_relationship_json(user, target, db))
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/:id
# ---------------------------------------------------------------------------
@router.get("/v1/accounts/{account_id}")
def get_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = db.query(User).filter_by(id=int(account_id)).first()
    if not user:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    viewer = _maybe_bearer(request, db)
    return _account_json(user, db, viewer=viewer)


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/:id/statuses
# ---------------------------------------------------------------------------
@router.get("/v1/accounts/{account_id}/statuses")
def get_account_statuses(
    account_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=100),
    pinned: bool | None = None,
    only_media: bool = False,
    exclude_reblogs: bool = False,
    exclude_replies: bool = False,
):
    user = _require_bearer(request, db)
    target_user = db.query(User).filter_by(id=int(account_id)).first()
    if not user:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    relationship = _relationship_json(user, target_user, db)
    viewer = _maybe_bearer(request, db)

    if pinned:
        pinned_ids = target_user.pinned_posts or []
        if not pinned_ids:
            return []
        q = db.query(Post).filter(
            Post.id.in_(pinned_ids),
            Post.is_deleted == False,
        )
    elif exclude_reblogs:
        q = db.query(Post).filter(
            Post.author_id == target_user.id,
            Post.is_deleted == False,
            Post.boost_of_id.is_(None),
        )
    else:
        q = db.query(Post).filter(
            Post.author_id == target_user.id,
            Post.is_deleted == False,
        )

    if exclude_replies:
        q = q.filter(Post.in_reply_to_id.is_(None))

    if only_media:
        q = q.filter(
            Post.media_attachments != None,
            cast(Post.media_attachments, String) != "[]",
            cast(Post.media_attachments, String) != "null",
        )

    if relationship.get('following') is False:
        q = q.filter(Post.visibility != "followers")
    if relationship.get('blocking') is True or relationship.get('blocked_by') is True:
        q = q.filter(False)

    if max_id:
        q = q.filter(Post.id < int(max_id))
    if since_id:
        q = q.filter(Post.id > int(since_id))
    if min_id:
        q = q.filter(Post.id > int(min_id))

    posts = q.order_by(Post.id.desc()).limit(limit).all()

    if only_media:
        posts = [p for p in posts if isinstance(p.media_attachments, list) and len(p.media_attachments) > 0]

    maps = _build_status_maps(posts, db, viewer)
    result = []
    for p in posts:
        if p.visibility == "mention" and user not in p.mentioned_user_ids:
            continue

        if p.boost_of_id:
            original = db.query(Post).filter_by(id=p.boost_of_id).first()
            if original and not original.is_deleted and original.author_id != target_user.id:
                s = _boost_status_json(p, original, db, viewer=viewer, **maps)
                if s:
                    result.append(s)
        else:
            s = _status_json(p, db, viewer=viewer, **maps)
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/:id/followers
# ---------------------------------------------------------------------------
@router.get("/v1/accounts/{account_id}/followers")
def get_account_followers(
    account_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=80),
):
    user = db.query(User).filter_by(id=int(account_id)).first()
    if not user:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    q = db.query(Follow).filter(Follow.following_id == user.id, Follow.accepted == True)
    if max_id:
        q = q.filter(Follow.id < int(max_id))

    follows = q.order_by(Follow.id.desc()).limit(limit).all()
    viewer = _maybe_bearer(request, db)
    counts = _build_account_counts_map({f.follower_id for f in follows}, db)
    return [_account_json(f.follower, db, viewer, _counts=counts.get(f.follower_id)) for f in follows]


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/:id/following
# ---------------------------------------------------------------------------
@router.get("/v1/accounts/{account_id}/following")
def get_account_following(
    account_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=80),
):
    user = db.query(User).filter_by(id=int(account_id)).first()
    if not user:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    q = db.query(Follow).filter(Follow.follower_id == user.id, Follow.accepted == True)
    if max_id:
        q = q.filter(Follow.id < int(max_id))

    follows = q.order_by(Follow.id.desc()).limit(limit).all()
    viewer = _maybe_bearer(request, db)
    counts = _build_account_counts_map({f.following_id for f in follows}, db)
    return [_account_json(f.following, db, viewer, _counts=counts.get(f.following_id)) for f in follows]


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/:id/follow
# ---------------------------------------------------------------------------
@router.post("/v1/accounts/{account_id}/follow")
async def follow_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    target = db.query(User).filter_by(id=int(account_id)).first()
    if not target:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    if target.id == user.id:
        raise MastodonAPIError(status_code=422, detail="Cannot follow self")

    follow_user(db, user, target)

    return _relationship_json(user, target, db)


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/:id/unfollow
# ---------------------------------------------------------------------------
@router.post("/v1/accounts/{account_id}/unfollow")
async def unfollow_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    target = db.query(User).filter_by(id=int(account_id)).first()
    if not target:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    unfollow_user(db, user, target)

    return _relationship_json(user, target, db)


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/:id/mute
# ---------------------------------------------------------------------------
@router.post("/v1/accounts/{account_id}/mute")
async def mute_account(account_id: str, request: Request, db: SASession = Depends(get_db),
                       notifications: bool = False):
    user = _require_bearer(request, db)
    target = db.query(User).filter_by(id=int(account_id)).first()
    if not target:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    if target.id == user.id:
        raise MastodonAPIError(status_code=422, detail="Cannot mute self")

    mute_user(db, user, target, hide_notifications=notifications)

    return _relationship_json(user, target, db)


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/:id/unmute
# ---------------------------------------------------------------------------
@router.post("/v1/accounts/{account_id}/unmute")
async def unmute_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    target = db.query(User).filter_by(id=int(account_id)).first()
    if not target:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    unmute_user(db, user, target)

    return _relationship_json(user, target, db)


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/:id/block
# ---------------------------------------------------------------------------
@router.post("/v1/accounts/{account_id}/block")
async def block_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    target = db.query(User).filter_by(id=int(account_id)).first()
    if not target:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    if target.id == user.id:
        raise MastodonAPIError(status_code=422, detail="Cannot block self")

    block_user(db, user, target)

    return _relationship_json(user, target, db)


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/:id/unblock
# ---------------------------------------------------------------------------
@router.post("/v1/accounts/{account_id}/unblock")
async def unblock_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    target = db.query(User).filter_by(id=int(account_id)).first()
    if not target:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    unblock_user(db, user, target)

    return _relationship_json(user, target, db)
