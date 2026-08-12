"""Mastodon status endpoints (/api/v1/statuses*, /api/v1/media)."""
import json
import os
import secrets

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import func as sqlfunc, or_
from sqlalchemy.orm import Session as SASession

from app.models import User, Post, Like, Boost, Bookmark, CustomEmoji, Follow
from app.db.database import get_db
from app.core.activitypub import _broadcast_update_actor
from app.core.threads import spawn
from app.routes.api import _do_edit_post, _do_delete_post
from app.core.interactions import like_post, unlike_post, boost_post, unboost_post, react_post, unreact_post
from app.utils.emoji import _load_emojis
from app.routes.mastodon_api._common import (
    MastodonAPIError,
    STAR_REACTION,
    _account_json,
    _build_account_counts_map,
    _build_status_maps,
    _maybe_bearer,
    _query_id_list,
    _require_bearer,
    _status_json,
    _visibility_from_mastodon,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id
# ---------------------------------------------------------------------------
@router.get("/v1/statuses/{status_id}")
def get_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    viewer = _maybe_bearer(request, db)
    if not viewer:
        s = _status_json(post, db, None)
    else:
        _liked_ids = {post.id} if db.query(Like).filter(
            Like.user_id == viewer.id, Like.post_id == post.id,
            or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
        ).first() else set()
        _boosted_ids = {post.id} if db.query(Boost).filter_by(user_id=viewer.id, post_id=post.id).first() else set()
        _bookmarked_ids = {post.id} if db.query(Bookmark).filter_by(user_id=viewer.id, post_id=post.id).first() else set()
        s = _status_json(post, db, viewer, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids)
    if s is None:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    return s


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/source
# ---------------------------------------------------------------------------
@router.get("/v1/statuses/{status_id}/source")
def get_status_source(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted or post.author_id != user.id:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    return {
        "id": str(post.id),
        "text": post.content or "",
        "spoiler_text": post.summary or "",
    }


# ---------------------------------------------------------------------------
# GET /api/v1/statuses (batch)
# ---------------------------------------------------------------------------
@router.get("/v1/statuses")
def get_statuses(
    request: Request,
    db: SASession = Depends(get_db),
    id: list[str] = Query(default=[]),
):
    viewer = _maybe_bearer(request, db)
    ids = id or _query_id_list(request)
    post_ids = []
    posts_map = {}
    for sid in ids:
        try:
            post = db.query(Post).filter_by(id=int(sid), is_deleted=False).first()
            if post:
                post_ids.append(post.id)
                posts_map[post.id] = post
        except ValueError:
            continue
    _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
        Like.user_id == viewer.id,
        or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
        Like.post_id.in_(post_ids)
    ).all()) if viewer and post_ids else set()
    _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
        Boost.user_id == viewer.id, Boost.post_id.in_(post_ids)
    ).all()) if viewer and post_ids else set()
    _bookmarked_ids = set(r[0] for r in db.query(Bookmark.post_id).filter(
        Bookmark.user_id == viewer.id, Bookmark.post_id.in_(post_ids)
    ).all()) if viewer and post_ids else set()
    maps = _build_status_maps(list(posts_map.values()), db, viewer)
    result = []
    for sid in ids:
        try:
            pid = int(sid)
            post = posts_map.get(pid)
            if post:
                s = _status_json(post, db, viewer, _liked_ids=_liked_ids,
                                 _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids, **maps)
                if s:
                    result.append(s)
        except ValueError:
            continue
    return result


# ---------------------------------------------------------------------------
# POST /api/v1/statuses
# ---------------------------------------------------------------------------
@router.post("/v1/statuses")
async def create_status(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)

    ct = request.headers.get("content-type", "")
    if "json" in ct:
        body = await request.json()
        text = body.get("status", "")
        in_reply_to_id = body.get("in_reply_to_id")
        sensitive = body.get("sensitive", False)
        spoiler_text = body.get("spoiler_text", "")
        visibility = body.get("visibility", user.default_visibility)
        language = body.get("language", "ko")
        media_ids = body.get("media_ids", [])
        poll_options = body.get("poll", {}).get("options") if body.get("poll") else None
        poll_expires = body.get("poll", {}).get("expires_in") if body.get("poll") else None
    else:
        form = await request.form()
        text = form.get("status", "")
        in_reply_to_id = form.get("in_reply_to_id")
        sensitive = form.get("sensitive", "false")
        spoiler_text = form.get("spoiler_text", "")
        visibility = form.get("visibility", user.default_visibility)
        language = form.get("language", "ko")
        media_ids = [v for k, v in form.multi_items() if k == "media_ids"]
        poll_options = form.get("poll[options]")
        poll_expires = form.get("poll[expires_in]")

    from fastapi.concurrency import run_in_threadpool
    return await run_in_threadpool(_run_create_status,
        db, user, text, in_reply_to_id, sensitive, spoiler_text,
        visibility, language, media_ids, poll_options, poll_expires,
    )


def _run_create_status(db, user, text, in_reply_to_id, sensitive, spoiler_text,
                        visibility, language, media_ids, poll_options, poll_expires):
    from app.routes.api._post_create import _do_create_post

    if not text and not media_ids:
        raise MastodonAPIError(status_code=422, detail="Validation failed: Text can't be blank")

    vis = _visibility_from_mastodon(visibility) if visibility in ("public", "unlisted", "private", "direct") else user.default_visibility

    media_attachments_json = "[]"
    if media_ids:
        media_attachments_json = json.dumps([
            {"url": f"/uploads/media/{mid}", "type": "image", "alt": ""}
            for mid in media_ids[:4]
        ])

    poll_options_json = ""
    if poll_options:
        if isinstance(poll_options, list):
            poll_options_json = json.dumps(poll_options)
        elif isinstance(poll_options, str):
            poll_options_json = poll_options

    poll_expires_minutes = 60
    if poll_expires:
        try:
            poll_expires_minutes = max(1, int(poll_expires) // 60)
        except (ValueError, TypeError):
            pass

    pj = _do_create_post(
        user.id, user.is_limited, getattr(user, 'is_sensitive', False),
        text, spoiler_text or "", vis,
        int(in_reply_to_id) if in_reply_to_id else None,
        None, "", media_attachments_json, bool(sensitive),
        poll_options_json, poll_expires_minutes, "",
    )
    post = db.query(Post).filter_by(id=pj["id"]).first()
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# PUT /api/v1/statuses/:id
# ---------------------------------------------------------------------------
@router.put("/v1/statuses/{status_id}")
async def update_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.author_id != user.id:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    ct = request.headers.get("content-type", "")
    if "multipart" in ct:
        form = await request.form()
        text = form.get("status", "")
        sensitive = form.get("sensitive", "false")
        spoiler_text = form.get("spoiler_text", "")
        visibility = form.get("visibility")
    elif "json" in ct:
        body = await request.json()
        text = body.get("status", "")
        sensitive = body.get("sensitive", False)
        spoiler_text = body.get("spoiler_text", "")
        visibility = body.get("visibility")
    else:
        form = await request.form()
        text = form.get("status", "")
        sensitive = form.get("sensitive", "false")
        spoiler_text = form.get("spoiler_text", "")
        visibility = form.get("visibility")

    vis = _visibility_from_mastodon(visibility) if visibility in ("public", "unlisted", "private", "direct") else None
    _do_edit_post(db, post, user, text, spoiler_text or "", visibility=vis, is_sensitive=bool(sensitive))
    db.refresh(post)
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# DELETE /api/v1/statuses/:id
# ---------------------------------------------------------------------------
@router.delete("/v1/statuses/{status_id}")
def delete_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.author_id != user.id:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    status_data = _status_json(post, db, viewer=user)
    _do_delete_post(db, post, user, cascade=False)
    return status_data


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/context
# ---------------------------------------------------------------------------
def _visible_in_thread(post: Post, viewer: User | None, following_ids: set, db: SASession) -> bool:
    """스레드 가시성 필터: 내가 팔로하지 않은 계정의 followers/mention 공개글은 제외."""
    if viewer and post.author_id == viewer.id:
        return True
    v = post.visibility or "public"
    if v in ("public", "home"):
        return True
    if not viewer:
        return False
    if v == "followers":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return post.author_id in following_ids
    if v == "mention":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return False
    return True


@router.get("/v1/statuses/{status_id}/context")
def get_status_context(status_id: str, request: Request, db: SASession = Depends(get_db)):
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    viewer = _maybe_bearer(request, db)
    following_ids = set()
    if viewer:
        following_ids = {row[0] for row in db.query(Follow.following_id).filter(
            Follow.follower_id == viewer.id, Follow.accepted == True
        ).all()}

    ancestors = []
    current = post.parent
    ancestor_posts = []
    while current and not current.is_deleted and len(ancestor_posts) < 40:
        ancestor_posts.append(current)
        current = current.parent
    ancestor_posts = [p for p in ancestor_posts if _visible_in_thread(p, viewer, following_ids, db)]
    maps = _build_status_maps(ancestor_posts, db, viewer)
    for cur in ancestor_posts:
        s = _status_json(cur, db, viewer, **maps)
        if s:
            ancestors.append(s)
    ancestors.reverse()

    descendants = []
    child_posts = db.query(Post).filter(
        Post.in_reply_to_id == post.id, Post.is_deleted == False
    ).order_by(Post.id.asc()).limit(60).all()
    queue = list(child_posts)
    all_descendants = []
    while queue:
        child = queue.pop(0)
        if _visible_in_thread(child, viewer, following_ids, db):
            all_descendants.append(child)
        grandchild = db.query(Post).filter(
            Post.in_reply_to_id == child.id, Post.is_deleted == False
        ).order_by(Post.id.asc()).limit(10).all()
        queue.extend(grandchild)
    maps2 = _build_status_maps(all_descendants, db, viewer)
    for child in all_descendants:
        s = _status_json(child, db, viewer, **maps2)
        if s:
            descendants.append(s)

    return {"ancestors": ancestors, "descendants": descendants}


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/favourite
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/favourite")
def favourite_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    like_post(db, user, post.id)

    return _status_json(post, db, viewer=user, _liked_ids={post.id})


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unfavourite
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/unfavourite")
def unfavourite_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    unlike_post(db, user, post.id)

    return _status_json(post, db, viewer=user, _liked_ids=set())


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/reblog
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/reblog")
def reblog_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    boost_post(db, user, post.id)

    return _status_json(post, db, viewer=user, _boosted_ids={post.id})


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unreblog
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/unreblog")
def unreblog_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    unboost_post(db, user, post.id)

    return _status_json(post, db, viewer=user, _boosted_ids=set())


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/bookmark
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/bookmark")
def bookmark_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    existing = db.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first()
    if not existing:
        bm = Bookmark(user_id=user.id, post_id=post.id)
        db.add(bm)
        db.commit()

    post = db.query(Post).filter_by(id=int(status_id)).first()
    return _status_json(post, db, viewer=user, _bookmarked_ids={post.id})


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unbookmark
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/unbookmark")
def unbookmark_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    existing = db.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first()
    if existing:
        db.delete(existing)
        db.commit()

    post = db.query(Post).filter_by(id=int(status_id)).first()
    return _status_json(post, db, viewer=user, _bookmarked_ids=set())


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/react/:name  (Glitch-soc)
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/react/{name}")
def react_to_status(status_id: str, name: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    if not name.startswith(":"):
        name = f":{name}"
    if not name.endswith(":"):
        name = f"{name}:"

    keyword = name.strip(":")
    emoji_row = db.query(CustomEmoji).filter_by(keyword=keyword, domain="").first()
    if not emoji_row:
        emoji_row = db.query(CustomEmoji).filter_by(keyword=keyword).first()
    if not emoji_row or (emoji_row.domain and emoji_row.domain.strip()):
        raise MastodonAPIError(status_code=400, detail="Remote emojis cannot be used as reactions")

    react_post(db, user, post.id, name)

    _liked_ids = {post.id} if name.strip(":") == STAR_REACTION else set()
    _boosted_ids = {post.id} if db.query(Boost).filter_by(user_id=user.id, post_id=post.id).first() else set()
    _bookmarked_ids = {post.id} if db.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first() else set()
    return _status_json(post, db, viewer=user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids)


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unreact/:name  (Glitch-soc)
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/unreact/{name}")
def unreact_to_status(status_id: str, name: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    if not name.startswith(":"):
        name = f":{name}"
    if not name.endswith(":"):
        name = f"{name}:"

    unreact_post(db, user, post.id, name)

    _liked_ids = {post.id} if db.query(Like).filter(
        Like.user_id == user.id, Like.post_id == post.id,
        or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
    ).first() else set()
    _boosted_ids = {post.id} if db.query(Boost).filter_by(user_id=user.id, post_id=post.id).first() else set()
    _bookmarked_ids = {post.id} if db.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first() else set()
    return _status_json(post, db, viewer=user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids)


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/reactions  (Glitch-soc)
# ---------------------------------------------------------------------------
@router.get("/v1/statuses/{status_id}/reactions")
def list_reactions(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _maybe_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    reaction_rows = db.query(
        Like.reaction, sqlfunc.count(Like.id), sqlfunc.min(Like.user_id)
    ).filter(Like.post_id == post.id).group_by(Like.reaction).order_by(sqlfunc.min(Like.id)).all()

    result = []
    for react, cnt, first_user_id in reaction_rows:
        name = react or "★"
        emoji_url = ""
        emoji_static_url = ""
        if name != "★":
            emoji_row = next((e for e in _load_emojis(db) if e["keyword"] == name.strip(":")), None)
            if emoji_row:
                emoji_url = emoji_row["url"]
                emoji_static_url = emoji_row["url"]
        first_user = db.query(User).filter_by(id=first_user_id).first()
        result.append({
            "name": name,
            "count": cnt,
            "me": user is not None and db.query(Like).filter_by(user_id=user.id, post_id=post.id, reaction=react).first() is not None,
            "url": emoji_url,
            "static_url": emoji_static_url,
            "account": _account_json(first_user, db, viewer=user) if first_user else None,
        })
    return result


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/mute
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/mute")
def mute_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unmute
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/unmute")
def unmute_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/pin
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/pin")
def pin_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.author_id != user.id:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    if post.visibility == "mention":
        raise MastodonAPIError(status_code=422, detail="Mention posts cannot be pinned")
    pinned = list(user.pinned_posts or [])
    if post.id not in pinned:
        if len(pinned) >= 5:
            raise MastodonAPIError(status_code=422, detail="Maximum of 5 pinned posts")
        pinned.append(post.id)
        db.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
    post.is_pinned = True
    db.commit()
    spawn(_broadcast_update_actor, user)
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unpin
# ---------------------------------------------------------------------------
@router.post("/v1/statuses/{status_id}/unpin")
def unpin_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.author_id != user.id:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    pinned = list(user.pinned_posts or [])
    if post.id in pinned:
        pinned.remove(post.id)
        db.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
    post.is_pinned = False
    db.commit()
    spawn(_broadcast_update_actor, user)
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/reblogged_by
# ---------------------------------------------------------------------------
@router.get("/v1/statuses/{status_id}/reblogged_by")
def reblogged_by(
    status_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=100),
):
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    q = db.query(Boost).filter(Boost.post_id == post.id)
    if max_id:
        q = q.filter(Boost.id < int(max_id))
    boosts = q.order_by(Boost.id.desc()).limit(limit).all()

    viewer = _maybe_bearer(request, db)
    counts = _build_account_counts_map({b.user_id for b in boosts}, db)
    return [_account_json(b.user, db, viewer, _counts=counts.get(b.user_id)) for b in boosts]


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/favourited_by
# ---------------------------------------------------------------------------
@router.get("/v1/statuses/{status_id}/favourited_by")
def favourited_by(
    status_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=100),
):
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    q = db.query(Like).filter(
        Like.post_id == post.id,
        or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
    )
    if max_id:
        q = q.filter(Like.id < int(max_id))
    likes = q.order_by(Like.id.desc()).limit(limit).all()

    viewer = _maybe_bearer(request, db)
    counts = _build_account_counts_map({l.user_id for l in likes}, db)
    return [_account_json(l.user, db, viewer, _counts=counts.get(l.user_id)) for l in likes]


# ---------------------------------------------------------------------------
# POST /api/v1/media
# ---------------------------------------------------------------------------
@router.post("/v1/media")
async def upload_media(
    request: Request,
    db: SASession = Depends(get_db),
    file: UploadFile = File(...),
    description: str = Form(""),
    focus: str = Form(""),
):
    user = _require_bearer(request, db)

    from app.utils.upload import _validate_upload

    ext, is_image, is_video, is_audio = _validate_upload(file, allow_video=True, allow_audio=True, label="미디어")
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "media")
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"{secrets.token_urlsafe(16)}{ext}"
    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    media_type = "image"
    if is_video:
        media_type = "video"
    elif is_audio:
        media_type = "audio"

    return {
        "id": filename,
        "type": media_type,
        "url": f"/uploads/media/{filename}",
        "preview_url": f"/uploads/media/{filename}",
        "remote_url": None,
        "text_url": f"/uploads/media/{filename}",
        "meta": {},
        "description": description,
        "blurhash": None,
    }
