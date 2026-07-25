"""Mastodon-compatible API endpoints (/api/v1/*).

Enables third-party Mastodon clients (Tusky, Metatext, etc.) to interact with WRIT.
"""
import secrets
import html
import re
import json
import logging
import threading
from datetime import datetime, timezone, timedelta as _timedelta

logger = logging.getLogger("writ.mastodon_api")

from fastapi import APIRouter, Request, HTTPException, Depends, Query, UploadFile, File, Form
from sqlalchemy import func as sqlfunc, or_
from sqlalchemy.orm import Session as SASession

from app.db.database import get_db
from app.config.settings import BASE_URL, DOMAIN, MAX_POST_LENGTH
from app.core.eventbus import broadcast as _broadcast_sse
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_refresh_notifs, broadcast_notif_sound, broadcast_post, broadcast_delete
from app.models import User, Post, Follow, Like, Boost, Bookmark, Notification, Tag, CustomEmoji, ServerSetting, MastodonApp, MastodonAccessToken, get_session, now
from app.utils.content_parser import process_post_content, extract_mentions
from app.utils.emoji import _emoji_url, _load_emojis
from app.db.mention_resolver import resolve_handles_to_ids
from app.routes.api import _sync_post_tags, _broadcast_update_actor
from app.serializers import _post_json

router = APIRouter()

VISIBILITY_MAP = {
    "public": "public",
    "home": "unlisted",
    "followers": "private",
    "mention": "direct",
    "dm": "direct",
}
VISIBILITY_MAP_REVERSE = {v: k for k, v in VISIBILITY_MAP.items()}
VISIBILITY_MAP_REVERSE["unlisted"] = "home"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_bearer_user(request: Request, db: SASession) -> User | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    mat = db.query(MastodonAccessToken).filter_by(access_token=token).first()
    if not mat:
        return None
    return db.query(User).filter_by(id=mat.user_id, is_remote=False).first()


def _require_bearer(request: Request, db: SASession) -> User:
    user = _get_bearer_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="The access token is invalid")
    if user.is_suspended:
        raise HTTPException(status_code=403, detail="Account suspended")
    if user.is_frozen:
        raise HTTPException(status_code=403, detail="Account frozen")
    return user


def _maybe_bearer(request: Request, db: SASession) -> User | None:
    return _get_bearer_user(request, db)


def _visibility_to_mastodon(vis: str) -> str:
    return VISIBILITY_MAP.get(vis, "public")


def _visibility_from_mastodon(vis: str) -> str:
    return VISIBILITY_MAP_REVERSE.get(vis, "public")


def _ap_datetime(dt) -> str:
    if dt is None:
        return now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _account_json(user: User, db: SASession, viewer: User | None = None) -> dict:
    follower_count = db.query(sqlfunc.count(Follow.id)).filter(
        Follow.following_id == user.id, Follow.accepted == True
    ).scalar() or 0
    following_count = db.query(sqlfunc.count(Follow.id)).filter(
        Follow.follower_id == user.id, Follow.accepted == True
    ).scalar() or 0
    statuses_count = db.query(sqlfunc.count(Post.id)).filter(
        Post.author_id == user.id, Post.is_deleted == False
    ).scalar() or 0

    acct = user.display_handle or user.username
    if acct.count('@') > 1:
        parts = acct.split('@')
        acct = f"{parts[0]}@{parts[1]}"

    # Mastodon API 규격: username은 로컬 부분만, acct에 전체 핸들
    if user.is_remote:
        username = user.username.split("@")[0] if "@" in user.username else user.username
    else:
        username = user.username

    display_name = user.display_name or ""
    note_html = f"<p>{user.summary}</p>" if user.summary else "<p></p>"
    source_note = user.summary or ""

    all_emojis = _load_emojis(db)
    shortcode_re = re.compile(r':(\w+):')
    used = set(shortcode_re.findall(display_name)) | set(shortcode_re.findall(source_note))
    emojis_in_account = [e for e in all_emojis if e["keyword"] in used]

    def _emoji_to_img(m):
        kw = m.group(1)
        emoji = next((e for e in emojis_in_account if e["keyword"] == kw), None)
        if emoji and emoji.get("url"):
            safe_url = emoji["url"].replace('"', "%22")
            return f'<img src="{safe_url}" alt=":{kw}:" title=":{kw}:" class="custom-emoji" style="display:inline-block;width:1.2em;height:1.2em;vertical-align:-0.2em;">'
        return m.group(0)
    note_html = shortcode_re.sub(_emoji_to_img, note_html)

    account = {
        "id": str(user.id),
        "username": username,
        "acct": acct,
        "display_name": display_name,
        "locked": bool(user.is_locked),
        "bot": bool(user.is_bot),
        "created_at": _ap_datetime(user.created_at),
        "note": note_html,
        "url": user.profile_url or (user.remote_url if user.is_remote else f"{BASE_URL}/@{username}"),
        "avatar": user.profile_image or f"{BASE_URL}/default-avatar.png",
        "avatar_static": user.profile_image or f"{BASE_URL}/default-avatar.png",
        "header": user.header_image or f"{BASE_URL}/default-header.png",
        "header_static": user.header_image or f"{BASE_URL}/default-header.png",
        "followers_count": follower_count,
        "following_count": following_count,
        "statuses_count": statuses_count,
        "last_status_at": _ap_datetime(user.updated_at) if user.updated_at else None,
        "emojis": [
            {"shortcode": e["keyword"], "url": e["url"], "static_url": e["url"], "visible_in_picker": True}
            for e in emojis_in_account
        ],
        "fields": [],
        "source": {
            "note": source_note,
            "privacy": _visibility_to_mastodon(user.default_visibility),
            "language": "ko",
            "follow_requests_count": 0,
        },
    }

    custom_fields = getattr(user, "custom_fields", None) or []
    for cf in custom_fields:
        name = cf.get("name") or cf.get("label", "")
        value = cf.get("value", "")
        if name:
            account["fields"].append({
                "name": name,
                "value": value,
                "verified_at": None,
            })

    if viewer:
        relationship = db.query(Follow).filter_by(
            follower_id=viewer.id, following_id=user.id
        ).first()
        account["relationship"] = {
            "id": str(user.id),
            "following": bool(relationship),
            "showing_reblogs": True,
            "notifying": bool(relationship and relationship.notify_on_post),
            "blocking": False,
            "muting": False,
            "domain_blocking": False,
            "endorsed": False,
        }

    return account


def _status_json(post: Post, db: SASession, viewer: User | None = None,
                 _boosted_ids: set = None, _liked_ids: set = None,
                 _bookmarked_ids: set = None) -> dict:
    if post.is_deleted:
        return None

    author = post.author
    if not author or author.is_suspended:
        return None

    content = post.content or ""

    all_emojis = _load_emojis(db)
    shortcode_pattern = re.compile(r':(\w+):')
    used_shortcodes = set(shortcode_pattern.findall(content))
    post_emojis = [e for e in all_emojis if e["keyword"] in used_shortcodes]

    def _emoji_to_img(m):
        kw = m.group(1)
        emoji = next((e for e in post_emojis if e["keyword"] == kw), None)
        if emoji and emoji.get("url"):
            safe_url = emoji["url"].replace('"', "%22")
            return f'<img src="{safe_url}" alt=":{kw}:" title=":{kw}:" class="custom-emoji" style="display:inline-block;width:1.2em;height:1.2em;vertical-align:-0.2em;">'
        return m.group(0)
    content = shortcode_pattern.sub(_emoji_to_img, content)

    replies_count = db.query(sqlfunc.count(Post.id)).filter(
        Post.in_reply_to_id == post.id, Post.is_deleted == False
    ).scalar() or 0
    reblogs_count = db.query(sqlfunc.count(Boost.id)).filter(
        Boost.post_id == post.id
    ).scalar() or 0
    favourites_count = db.query(sqlfunc.count(Like.id)).filter(
        Like.post_id == post.id
    ).scalar() or 0

    status = {
        "id": str(post.id),
        "created_at": _ap_datetime(post.created_at),
        "in_reply_to_id": str(post.in_reply_to_id) if post.in_reply_to_id else None,
        "in_reply_to_account_id": None,
        "sensitive": bool(post.is_sensitive),
        "spoiler_text": post.summary or "",
        "visibility": _visibility_to_mastodon(post.visibility),
        "language": "ko",
        "uri": post.ap_id or f"{BASE_URL}/posts/{post.id}",
        "url": f"{BASE_URL}/@{author.username}/{post.id}",
        "replies_count": replies_count,
        "reblogs_count": reblogs_count,
        "favourites_count": favourites_count,
        "favourited": False,
        "reblogged": False,
        "muted": False,
        "bookmarked": False,
        "pinned": bool(post.is_pinned),
        "content": content if content.strip().startswith("<") else f"<p>{content}</p>",
        "reblog": None,
        "application": None,
        "account": _account_json(author, db),
        "media_attachments": [],
        "mentions": [],
        "tags": [],
        "emojis": [],
        "card": None,
        "poll": None,
        "reactions": [],
    }

    if post.in_reply_to_id and post.parent:
        status["in_reply_to_account_id"] = str(post.parent.author_id)

    if post.media_attachments:
        for m in post.media_attachments:
            status["media_attachments"].append({
                "id": str(m.get("id", "")),
                "type": m.get("type", "image"),
                "url": m.get("url", ""),
                "preview_url": m.get("preview_url", m.get("url", "")),
                "remote_url": None,
                "text_url": m.get("url", ""),
                "meta": {},
                "description": m.get("alt", ""),
                "blurhash": None,
            })

    if post.tag_list:
        for tag in post.tag_list:
            display = tag.display_name or tag.name
            status["tags"].append({
                "name": display,
                "url": f"{BASE_URL}/explore?q=%23{display}",
            })

    if post.poll_data:
        pd = post.poll_data
        options = pd.get("options", [])
        total_votes = sum(o.get("votes_count", 0) for o in options)
        status["poll"] = {
            "id": str(post.id),
            "expires_at": pd.get("expires_at"),
            "expired": False,
            "multiple": pd.get("multiple", False),
            "votes_count": total_votes,
            "voters_count": total_votes,
            "voted": False,
            "own_votes": [],
            "options": [{"title": o.get("text", ""), "votes_count": o.get("votes_count", 0)} for o in options],
        "emojis": [{
            "shortcode": e["keyword"],
            "url": e["url"],
            "static_url": e["url"],
            "visible_in_picker": True,
        } for e in post_emojis],
        }

    if viewer:
        if _liked_ids is None:
            _liked_ids = set()
        if _boosted_ids is None:
            _boosted_ids = set()
        if _bookmarked_ids is None:
            _bookmarked_ids = set()
        status["favourited"] = post.id in _liked_ids
        status["reblogged"] = post.id in _boosted_ids
        status["bookmarked"] = post.id in _bookmarked_ids

    reaction_rows = db.query(
        sqlfunc.coalesce(Like.reaction, "★"), sqlfunc.count(Like.id)
    ).filter(Like.post_id == post.id).group_by(Like.reaction).order_by(sqlfunc.min(Like.id)).all()
    my_reaction = None
    if viewer:
        my_like = db.query(Like).filter_by(user_id=viewer.id, post_id=post.id).first()
        if my_like:
            my_reaction = my_like.reaction or "★"
    for react, cnt in reaction_rows:
        name = react or "★"
        status["reactions"].append({
            "name": name,
            "count": cnt,
            "me": name == my_reaction,
        })

    return status


def _boost_status_json(boost_post: Post, original: Post, db: SASession,
                       viewer: User | None = None, **kwargs) -> dict:
    inner = _status_json(original, db, viewer, **kwargs)
    if inner is None:
        return None
    outer = _status_json(boost_post, db, viewer, **kwargs)
    if outer is None:
        return None
    outer["reblog"] = inner
    return outer


# ---------------------------------------------------------------------------
# POST /api/v1/apps — Register client application
# ---------------------------------------------------------------------------
@router.post("/apps")
async def create_app(request: Request, db: SASession = Depends(get_db)):
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    client_name = body.get("client_name") or "WRIT Client"
    redirect_uris = body.get("redirect_uris", "urn:ietf:wg:oauth:2.0:oob")
    if isinstance(redirect_uris, list):
        redirect_uris = "\n".join(redirect_uris)
    scopes = body.get("scopes", "read write push")
    website = body.get("website", "")

    client_id = secrets.token_urlsafe(32)
    client_secret = secrets.token_urlsafe(48)

    app = MastodonApp(
        client_name=client_name,
        redirect_uris=redirect_uris,
        scopes=scopes,
        website=website,
        client_id=client_id,
        client_secret=client_secret,
    )
    db.add(app)
    db.commit()
    db.refresh(app)

    return {
        "id": str(app.id),
        "name": app.client_name,
        "website": app.website or None,
        "scopes": app.scopes.split(),
        "redirect_uri": app.redirect_uris,
        "redirect_uris": app.redirect_uris.split("\n"),
        "client_id": app.client_id,
        "client_secret": app.client_secret,
        "client_secret_expires_at": 0,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/apps/verify_credentials
# ---------------------------------------------------------------------------
@router.get("/apps/verify_credentials")
def verify_app_credentials(request: Request, db: SASession = Depends(get_db)):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="The access token is invalid")
    token = auth[7:]
    mat = db.query(MastodonAccessToken).filter_by(access_token=token).first()
    if not mat:
        raise HTTPException(status_code=401, detail="The access token is invalid")
    app = db.query(MastodonApp).filter_by(id=mat.app_id).first()
    if not app:
        raise HTTPException(status_code=401, detail="The access token is invalid")
    return {
        "id": str(app.id),
        "name": app.client_name,
        "website": app.website or None,
        "scopes": app.scopes.split(),
        "redirect_uris": app.redirect_uris.split("\n"),
        "vapid_key": "",
    }


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/verify_credentials
# ---------------------------------------------------------------------------
@router.get("/accounts/verify_credentials")
def verify_account_credentials(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return _account_json(user, db, viewer=user)


# ---------------------------------------------------------------------------
# PATCH /api/v1/accounts/update_credentials
# ---------------------------------------------------------------------------
@router.patch("/accounts/update_credentials")
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
@router.get("/accounts/relationships")
def get_relationships(
    request: Request,
    db: SASession = Depends(get_db),
    id: list[str] = Query(default=[]),
):
    user = _require_bearer(request, db)
    result = []
    for uid in id:
        try:
            uid_int = int(uid)
        except ValueError:
            continue
        follow = db.query(Follow).filter_by(follower_id=user.id, following_id=uid_int).first()
        result.append({
            "id": uid,
            "following": bool(follow),
            "showing_reblogs": True,
            "notifying": bool(follow and follow.notify_on_post),
            "blocking": False,
            "muting": False,
            "domain_blocking": False,
            "endorsed": False,
            "followed_by": bool(db.query(Follow).filter_by(follower_id=uid_int, following_id=user.id).first()),
            "note": "",
        })
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/:id
# ---------------------------------------------------------------------------
@router.get("/accounts/{account_id}")
def get_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = db.query(User).filter_by(id=int(account_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Record not found")
    viewer = _maybe_bearer(request, db)
    return _account_json(user, db, viewer=viewer)


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/:id/statuses
# ---------------------------------------------------------------------------
@router.get("/accounts/{account_id}/statuses")
def get_account_statuses(
    account_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=80),
    pinned: bool | None = None,
):
    user = db.query(User).filter_by(id=int(account_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Record not found")

    viewer = _maybe_bearer(request, db)

    if pinned:
        pinned_ids = user.pinned_posts or []
        if not pinned_ids:
            return []
        q = db.query(Post).filter(
            Post.id.in_(pinned_ids),
            Post.is_deleted == False,
        )
    else:
        q = db.query(Post).filter(
            Post.author_id == user.id,
            Post.is_deleted == False,
            Post.boost_of_id.is_(None),
        )

    if max_id:
        q = q.filter(Post.id < int(max_id))
    if since_id:
        q = q.filter(Post.id > int(since_id))
    if min_id:
        q = q.filter(Post.id > int(min_id))

    posts = q.order_by(Post.id.desc()).limit(limit).all()

    result = []
    for p in posts:
        s = _status_json(p, db, viewer)
        if s:
            result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/:id/followers
# ---------------------------------------------------------------------------
@router.get("/accounts/{account_id}/followers")
def get_account_followers(
    account_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=80),
):
    user = db.query(User).filter_by(id=int(account_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Record not found")

    q = db.query(Follow).filter(Follow.following_id == user.id, Follow.accepted == True)
    if max_id:
        q = q.filter(Follow.id < int(max_id))

    follows = q.order_by(Follow.id.desc()).limit(limit).all()
    viewer = _maybe_bearer(request, db)
    return [_account_json(f.follower, db, viewer) for f in follows]


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/:id/following
# ---------------------------------------------------------------------------
@router.get("/accounts/{account_id}/following")
def get_account_following(
    account_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=80),
):
    user = db.query(User).filter_by(id=int(account_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Record not found")

    q = db.query(Follow).filter(Follow.follower_id == user.id, Follow.accepted == True)
    if max_id:
        q = q.filter(Follow.id < int(max_id))

    follows = q.order_by(Follow.id.desc()).limit(limit).all()
    viewer = _maybe_bearer(request, db)
    return [_account_json(f.following, db, viewer) for f in follows]


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/:id/follow
# ---------------------------------------------------------------------------
@router.post("/accounts/{account_id}/follow")
async def follow_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    target = db.query(User).filter_by(id=int(account_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="Record not found")
    if target.id == user.id:
        raise HTTPException(status_code=422, detail="Cannot follow self")

    existing = db.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
    if existing:
        if not existing.accepted:
            existing.accepted = True
            db.commit()
    else:
        follow = Follow(follower_id=user.id, following_id=target.id, accepted=True)
        db.add(follow)
        db.commit()

    viewer = _maybe_bearer(request, db)
    return _account_json(target, db, viewer)


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/:id/unfollow
# ---------------------------------------------------------------------------
@router.post("/accounts/{account_id}/unfollow")
async def unfollow_account(account_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    target = db.query(User).filter_by(id=int(account_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="Record not found")

    follow = db.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
    if follow:
        db.delete(follow)
        db.commit()

    viewer = _maybe_bearer(request, db)
    return _account_json(target, db, viewer)


# ---------------------------------------------------------------------------
# GET /api/v1/timelines/home
# ---------------------------------------------------------------------------
@router.get("/timelines/home")
def home_timeline(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=80),
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
        Post.boost_of_id.is_(None),
    )

    if max_id:
        q = q.filter(Post.id < int(max_id))
    if since_id:
        q = q.filter(Post.id > int(since_id))
    if min_id:
        q = q.filter(Post.id > int(min_id))

    posts = q.order_by(Post.id.desc()).limit(limit).all()

    _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
        Like.user_id == user.id, Like.post_id.in_([p.id for p in posts])
    ).all()) if posts else set()
    _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
        Boost.user_id == user.id, Boost.post_id.in_([p.id for p in posts])
    ).all()) if posts else set()
    _bookmarked_ids = set(r[0] for r in db.query(Bookmark.post_id).filter(
        Bookmark.user_id == user.id, Bookmark.post_id.in_([p.id for p in posts])
    ).all()) if posts else set()

    following_set = set(following_ids)

    result = []
    for p in posts:
        if p.boost_of_id:
            original = db.query(Post).filter_by(id=p.boost_of_id).first()
            if original and not original.is_deleted:
                # Reply filtering for boosted replies
                if original.in_reply_to_id:
                    parent = db.query(Post).filter_by(id=original.in_reply_to_id).first()
                    if parent and parent.author_id not in following_set and parent.author_id != user.id:
                        continue
                s = _boost_status_json(p, original, db, viewer=user,
                                       _boosted_ids=_boosted_ids, _liked_ids=_liked_ids,
                                       _bookmarked_ids=_bookmarked_ids)
                if s:
                    result.append(s)
        else:
            # Reply filtering: drop replies to posts by non-followed, non-self users
            if p.in_reply_to_id:
                parent = db.query(Post).filter_by(id=p.in_reply_to_id).first()
                if parent and parent.author_id not in following_set and parent.author_id != user.id:
                    continue
            s = _status_json(p, db, viewer=user, _boosted_ids=_boosted_ids,
                             _liked_ids=_liked_ids, _bookmarked_ids=_bookmarked_ids)
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/timelines/public
# ---------------------------------------------------------------------------
@router.get("/timelines/public")
def public_timeline(
    request: Request,
    db: SASession = Depends(get_db),
    local: bool = False,
    remote: bool = False,
    only_media: bool = False,
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=80),
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
        q = q.filter(Post.media_attachments != None, Post.media_attachments != "[]")

    if max_id:
        q = q.filter(Post.id < int(max_id))
    if since_id:
        q = q.filter(Post.id > int(since_id))
    if min_id:
        q = q.filter(Post.id > int(min_id))

    posts = q.order_by(Post.id.desc()).limit(limit).all()

    _liked_ids = set()
    _boosted_ids = set()
    _bookmarked_ids = set()
    if viewer:
        post_ids = [p.id for p in posts]
        _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
            Like.user_id == viewer.id, Like.post_id.in_(post_ids)
        ).all()) if post_ids else set()
        _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
            Boost.user_id == viewer.id, Boost.post_id.in_(post_ids)
        ).all()) if post_ids else set()
        _bookmarked_ids = set(r[0] for r in db.query(Bookmark.post_id).filter(
            Bookmark.user_id == viewer.id, Bookmark.post_id.in_(post_ids)
        ).all()) if post_ids else set()

    result = []
    for p in posts:
        if p.boost_of_id:
            original = db.query(Post).filter_by(id=p.boost_of_id).first()
            if original and not original.is_deleted:
                s = _boost_status_json(p, original, db, viewer=viewer,
                                       _boosted_ids=_boosted_ids, _liked_ids=_liked_ids,
                                       _bookmarked_ids=_bookmarked_ids)
                if s:
                    result.append(s)
        else:
            s = _status_json(p, db, viewer=viewer, _boosted_ids=_boosted_ids,
                             _liked_ids=_liked_ids, _bookmarked_ids=_bookmarked_ids)
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/timelines/tag/:tag
# ---------------------------------------------------------------------------
@router.get("/timelines/tag/{tag}")
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
    limit: int = Query(default=20, le=80),
):
    viewer = _maybe_bearer(request, db)
    tag_obj = db.query(Tag).filter(Tag.name == tag.lower()).first()
    if not tag_obj:
        raise HTTPException(status_code=404, detail="Record not found")

    q = db.query(Post).filter(
        Post.tag_list.any(Tag.id == tag_obj.id),
        Post.visibility == "public",
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

    _liked_ids = set()
    _boosted_ids = set()
    _bookmarked_ids = set()
    if viewer:
        post_ids = [p.id for p in posts]
        if post_ids:
            _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
                Like.user_id == viewer.id, Like.post_id.in_(post_ids)
            ).all())
            _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
                Boost.user_id == viewer.id, Boost.post_id.in_(post_ids)
            ).all())
            _bookmarked_ids = set(r[0] for r in db.query(Bookmark.post_id).filter(
                Bookmark.user_id == viewer.id, Bookmark.post_id.in_(post_ids)
            ).all())

    result = []
    for p in posts:
        s = _status_json(p, db, viewer=viewer, _boosted_ids=_boosted_ids,
                         _liked_ids=_liked_ids, _bookmarked_ids=_bookmarked_ids)
        if s:
            result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id
# ---------------------------------------------------------------------------
@router.get("/statuses/{status_id}")
def get_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")
    viewer = _maybe_bearer(request, db)
    if not viewer:
        s = _status_json(post, db, None)
    else:
        _liked_ids = {post.id} if db.query(Like).filter_by(user_id=viewer.id, post_id=post.id).first() else set()
        _boosted_ids = {post.id} if db.query(Boost).filter_by(user_id=viewer.id, post_id=post.id).first() else set()
        _bookmarked_ids = {post.id} if db.query(Bookmark).filter_by(user_id=viewer.id, post_id=post.id).first() else set()
        s = _status_json(post, db, viewer, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids)
    if s is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return s


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/source
# ---------------------------------------------------------------------------
@router.get("/statuses/{status_id}/source")
def get_status_source(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted or post.author_id != user.id:
        raise HTTPException(status_code=404, detail="Record not found")
    return {
        "id": str(post.id),
        "text": post.content or "",
        "spoiler_text": post.summary or "",
    }


# ---------------------------------------------------------------------------
# GET /api/v1/statuses (batch)
# ---------------------------------------------------------------------------
@router.get("/statuses")
def get_statuses(
    request: Request,
    db: SASession = Depends(get_db),
    id: list[str] = Query(default=[]),
):
    viewer = _maybe_bearer(request, db)
    post_ids = []
    posts_map = {}
    for sid in id:
        try:
            post = db.query(Post).filter_by(id=int(sid), is_deleted=False).first()
            if post:
                post_ids.append(post.id)
                posts_map[post.id] = post
        except ValueError:
            continue
    _liked_ids = set(r[0] for r in db.query(Like.post_id).filter(
        Like.user_id == viewer.id, Like.post_id.in_(post_ids)
    ).all()) if viewer and post_ids else set()
    _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
        Boost.user_id == viewer.id, Boost.post_id.in_(post_ids)
    ).all()) if viewer and post_ids else set()
    _bookmarked_ids = set(r[0] for r in db.query(Bookmark.post_id).filter(
        Bookmark.user_id == viewer.id, Bookmark.post_id.in_(post_ids)
    ).all()) if viewer and post_ids else set()
    result = []
    for sid in id:
        try:
            pid = int(sid)
            post = posts_map.get(pid)
            if post:
                s = _status_json(post, db, viewer, _liked_ids=_liked_ids,
                                 _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids)
                if s:
                    result.append(s)
        except ValueError:
            continue
    return result


# ---------------------------------------------------------------------------
# POST /api/v1/statuses
# ---------------------------------------------------------------------------
@router.post("/statuses")
async def create_status(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)

    ct = request.headers.get("content-type", "")
    if "multipart" in ct:
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
    elif "json" in ct:
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

    if not text and not media_ids:
        raise HTTPException(status_code=422, detail="Validation failed: Text can't be blank")

    vis = _visibility_from_mastodon(visibility) if visibility in ("public", "unlisted", "private", "direct") else user.default_visibility

    if vis in ("public", "home") and in_reply_to_id:
        parent = db.query(Post).filter_by(id=int(in_reply_to_id)).first()
        if parent:
            vis_order = {"public": 0, "home": 1, "followers": 2, "mention": 3}
            parent_vis = parent.visibility or "public"
            if vis_order.get(parent_vis, 0) > vis_order.get(vis, 0):
                vis = parent_vis

    content_html = process_post_content(text, None)
    mentions = extract_mentions(text, None)
    mentioned_handles = [m["handle"] for m in mentions]
    mentioned_ids = resolve_handles_to_ids(mentioned_handles)
    mentioned_ids = list(set(mentioned_ids))

    if not content_html.strip() and not poll_options:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    total_len = len(text) + len(spoiler_text or "")
    if total_len > MAX_POST_LENGTH:
        raise HTTPException(status_code=400, detail=f"Total length exceeds {MAX_POST_LENGTH}")

    if user.is_limited and vis == "public":
        vis = "home"

    post_number = secrets.token_hex(4)
    author_is_sensitive = getattr(user, 'is_sensitive', False) or False
    post = Post(
        author_id=user.id,
        content=content_html,
        summary=spoiler_text[:512] if spoiler_text else "",
        visibility=vis,
        is_sensitive=bool(sensitive) or author_is_sensitive,
        mentioned_user_ids=mentioned_ids,
        number=post_number,
        ap_id="",
    )

    if in_reply_to_id:
        parent = db.query(Post).filter_by(id=int(in_reply_to_id)).first()
        if parent:
            post.in_reply_to_id = parent.id
            post.in_reply_to_ap_id = parent.ap_id or ""

    db.add(post)
    db.flush()

    post.ap_id = f"{BASE_URL}/@{user.username}/{post.number}"

    if media_ids:
        post.media_attachments = [{"id": str(mid), "url": "", "type": "image", "alt": ""} for mid in media_ids[:4]]

    if poll_options:
        try:
            opts = json.loads(poll_options) if isinstance(poll_options, str) else poll_options
            if isinstance(opts, list) and 2 <= len(opts) <= 10 and all(isinstance(o, str) and o.strip() for o in opts):
                expires_in = int(poll_expires) if poll_expires else 60
                now_dt = datetime.now(timezone.utc)
                expires_at = (now_dt + _timedelta(minutes=expires_in)).isoformat() if expires_in > 0 else None
                post.poll_data = {
                    "options": [{"text": o.strip(), "votes_count": 0} for o in opts],
                    "expires_at": expires_at,
                }
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    _sync_post_tags(post, db)
    db.commit()
    db.refresh(post)

    pj = _post_json(post, db, user)

    from app.routes.api import _broadcast_federation, _broadcast_timeline

    def _create_notifications_and_broadcast():
        try:
            with get_session() as ns:
                mentioned_notified = set()
                for mu_id in mentioned_ids:
                    if mu_id != user.id:
                        notif = Notification(user_id=mu_id, from_user_id=user.id, notification_type="mention", post_id=post.id)
                        ns.add(notif)
                        mentioned_notified.add(mu_id)
                if in_reply_to_id:
                    parent = ns.query(Post).filter_by(id=in_reply_to_id).first()
                    if parent and parent.author_id != user.id and parent.author_id not in mentioned_notified:
                        notif = Notification(user_id=parent.author_id, from_user_id=user.id, notification_type="reply", post_id=post.id)
                        ns.add(notif)
                ns.commit()

            for mu_id in mentioned_ids:
                if mu_id != user.id:
                    send_push_to_user(mu_id, "mention", user.username, post.id)
                    broadcast_notif_sound(mu_id)
                    broadcast_refresh_notifs(mu_id)
            if in_reply_to_id:
                with get_session() as ps:
                    parent = ps.query(Post).filter_by(id=in_reply_to_id).first()
                if parent and parent.author_id != user.id and parent.author_id not in [mid for mid in mentioned_ids if mid != user.id]:
                    send_push_to_user(parent.author_id, "reply", user.username, post.id)
                    broadcast_notif_sound(parent.author_id)
                    broadcast_refresh_notifs(parent.author_id)
        except Exception as e:
            logger.error("Mastodon API: Failed to create notifications: %s", e, exc_info=True)

    threading.Thread(target=_create_notifications_and_broadcast, daemon=True).start()
    threading.Thread(target=_broadcast_federation, args=(user.id, post.id, vis, text), daemon=True).start()

    try:
        _broadcast_sse("new_post", {"post_id": post.id, "author_id": user.id})
    except Exception as e:
        logger.error("Mastodon API: Failed to broadcast new_post event: %s", e, exc_info=True)

    pj = _post_json(post, db, user)
    threading.Thread(target=_broadcast_timeline, args=(pj, user.id, vis, False), daemon=True).start()
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# PUT /api/v1/statuses/:id
# ---------------------------------------------------------------------------
@router.put("/statuses/{status_id}")
async def update_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.author_id != user.id:
        raise HTTPException(status_code=404, detail="Record not found")

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

    if post.summary and post.summary.startswith("[관리자 강제] ") and not (spoiler_text or "").startswith("[관리자 강제] "):
        raise HTTPException(status_code=403, detail="관리자가 강제한 CW는 수정할 수 없습니다")

    new_content = text.replace('\r\n', '\n').replace('\r', '\n') if text else post.content
    post.content = process_post_content(new_content, post=post)
    if spoiler_text is not None:
        post.summary = spoiler_text[:512]
    if visibility and visibility in ("public", "unlisted", "private", "direct"):
        post.visibility = _visibility_from_mastodon(visibility)
    post.is_sensitive = bool(sensitive)

    _sync_post_tags(post, db)
    db.commit()
    db.refresh(post)

    try:
        _ua = post.author
        broadcast_post({
            "id": post.id, "number": post.number or "",
            "content": post.content, "summary": post.summary or "",
            "visibility": post.visibility or "public",
            "created_at": post.created_at.isoformat() if post.created_at else "",
            "author": {
                "id": _ua.id, "username": _ua.username,
                "display_name": _ua.display_name or _ua.username,
                "avatar": _ua.profile_image or "", "header": _ua.header_image or "",
                "summary": _ua.summary or "", "is_admin": _ua.is_admin,
                "is_remote": _ua.is_remote,
            },
        }, post.author_id, post.visibility or "public")
    except Exception:
        pass

    if post.ap_id and not post.author.is_remote:
        def _bg_federation():
            try:
                import datetime as _dt
                note_data = post.to_ap_note()
                note_data.pop("@context", None)
                note_data.pop("url", None)
                note_data["atomUri"] = post.ap_id
                note_data["updated"] = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
                note_data.setdefault("summary", None)
                note_data.setdefault("sensitive", False)
                note_data.setdefault("attachment", [])
                note_data.setdefault("tag", [])
                note_data.setdefault("inReplyTo", None)
                update_activity = {
                    "@context": [
                        "https://www.w3.org/ns/activitystreams",
                        "https://w3id.org/security/v1",
                    ],
                    "id": f"{BASE_URL}/activities/update/{post.id}",
                    "type": "Update",
                    "actor": user.actor_uri(),
                    "to": note_data.get("to", []),
                    "cc": note_data.get("cc", []),
                    "object": note_data,
                }
                from app.activitypub import broadcast_to_followers
                broadcast_to_followers(user, update_activity)
            except Exception as e:
                logger.error("Mastodon API: Update federation failed: %s", e, exc_info=True)
        threading.Thread(target=_bg_federation, daemon=True).start()

    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# DELETE /api/v1/statuses/:id
# ---------------------------------------------------------------------------
@router.delete("/statuses/{status_id}")
def delete_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.author_id != user.id:
        raise HTTPException(status_code=404, detail="Record not found")

    media = list(post.media_attachments or [])
    ap_id = post.ap_id or ""
    is_remote_author = bool(post.author.is_remote)
    status_data = _status_json(post, db, viewer=user)
    post.content = ""
    post.media_attachments = []
    post.poll_data = None
    post.link_preview = None
    post.is_deleted = True
    db.query(Notification).filter_by(post_id=post.id).delete()
    db.commit()

    try:
        broadcast_delete(post.id)
        broadcast_refresh_notifs(post.author_id)
    except Exception:
        pass

    if ap_id and ap_id.startswith("http") and not is_remote_author:
        def _bg_delete():
            try:
                from app.activitypub import _send_delete_post
                with get_session() as s:
                    p = s.query(Post).filter_by(id=post.id).first()
                    if p:
                        _send_delete_post(p, user)
            except Exception as e:
                logger.error("Mastodon API: Failed to send delete activity: %s", e, exc_info=True)
        threading.Thread(target=_bg_delete, daemon=True).start()

    if media:
        def _bg_media():
            try:
                from app.utils.storage import get_storage
                storage = get_storage()
                for m in media:
                    if isinstance(m, dict) and m.get("url"):
                        try:
                            storage.delete(m["url"])
                        except Exception:
                            pass
            except Exception:
                pass
        threading.Thread(target=_bg_media, daemon=True).start()

    return status_data


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/context
# ---------------------------------------------------------------------------
@router.get("/statuses/{status_id}/context")
def get_status_context(status_id: str, request: Request, db: SASession = Depends(get_db)):
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    viewer = _maybe_bearer(request, db)

    ancestors = []
    current = post.parent
    while current and not current.is_deleted and len(ancestors) < 40:
        s = _status_json(current, db, viewer)
        if s:
            ancestors.append(s)
        current = current.parent
    ancestors.reverse()

    descendants = []
    child_posts = db.query(Post).filter(
        Post.in_reply_to_id == post.id, Post.is_deleted == False
    ).order_by(Post.id.asc()).limit(60).all()
    queue = list(child_posts)
    while queue:
        child = queue.pop(0)
        s = _status_json(child, db, viewer)
        if s:
            descendants.append(s)
        grandchild = db.query(Post).filter(
            Post.in_reply_to_id == child.id, Post.is_deleted == False
        ).order_by(Post.id.asc()).limit(10).all()
        queue.extend(grandchild)

    return {"ancestors": ancestors, "descendants": descendants}


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/favourite
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/favourite")
def favourite_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post.id).first()
    if not existing:
        like = Like(user_id=user.id, post_id=post.id)
        db.add(like)
        db.commit()

    post = db.query(Post).filter_by(id=int(status_id)).first()
    return _status_json(post, db, viewer=user, _liked_ids={post.id})


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unfavourite
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/unfavourite")
def unfavourite_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post.id).first()
    if existing:
        db.delete(existing)
        db.commit()

    post = db.query(Post).filter_by(id=int(status_id)).first()
    return _status_json(post, db, viewer=user, _liked_ids=set())


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/reblog
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/reblog")
def reblog_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    existing = db.query(Boost).filter_by(user_id=user.id, post_id=post.id).first()
    if existing:
        return _status_json(post, db, viewer=user, _boosted_ids={post.id})

    boost = Boost(user_id=user.id, post_id=post.id)
    db.add(boost)
    db.flush()

    boost_post = Post(
        author_id=user.id,
        content="",
        visibility="public",
        boost_of_id=post.id,
    )
    db.add(boost_post)
    db.commit()
    db.refresh(post)

    return _status_json(post, db, viewer=user, _boosted_ids={post.id})


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unreblog
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/unreblog")
def unreblog_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    existing = db.query(Boost).filter_by(user_id=user.id, post_id=post.id).first()
    if existing:
        db.delete(existing)
        db.query(Post).filter(
            Post.author_id == user.id, Post.boost_of_id == post.id
        ).delete(synchronize_session=False)
        db.commit()

    post = db.query(Post).filter_by(id=int(status_id)).first()
    return _status_json(post, db, viewer=user, _boosted_ids=set())


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/bookmark
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/bookmark")
def bookmark_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

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
@router.post("/statuses/{status_id}/unbookmark")
def unbookmark_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    existing = db.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first()
    if existing:
        db.delete(existing)
        db.commit()

    post = db.query(Post).filter_by(id=int(status_id)).first()
    return _status_json(post, db, viewer=user, _bookmarked_ids=set())


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/react/:name  (Glitch-soc)
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/react/{name}")
def react_to_status(status_id: str, name: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    if not name.startswith(":"):
        name = f":{name}"
    if not name.endswith(":"):
        name = f"{name}:"

    keyword = name.strip(":")
    emoji_row = db.query(CustomEmoji).filter_by(keyword=keyword, domain="").first()
    if not emoji_row:
        emoji_row = db.query(CustomEmoji).filter_by(keyword=keyword).first()
    if not emoji_row or (emoji_row.domain and emoji_row.domain.strip()):
        raise HTTPException(status_code=400, detail="Remote emojis cannot be used as reactions")

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post.id).first()
    if existing:
        if existing.reaction == name:
            return _status_json(post, db, viewer=user)
        existing.reaction = name
        db.commit()
    else:
        like = Like(user_id=user.id, post_id=post.id, reaction=name)
        db.add(like)
        db.commit()

    post = db.query(Post).filter_by(id=int(status_id)).first()
    _liked_ids = {post.id}
    _boosted_ids = {post.id} if db.query(Boost).filter_by(user_id=user.id, post_id=post.id).first() else set()
    _bookmarked_ids = {post.id} if db.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first() else set()
    return _status_json(post, db, viewer=user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids)


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unreact/:name  (Glitch-soc)
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/unreact/{name}")
def unreact_to_status(status_id: str, name: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    if not name.startswith(":"):
        name = f":{name}"
    if not name.endswith(":"):
        name = f"{name}:"

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post.id).first()
    if existing and existing.reaction == name:
        db.delete(existing)
        db.commit()

    post = db.query(Post).filter_by(id=int(status_id)).first()
    _liked_ids = {post.id} if db.query(Like).filter_by(user_id=user.id, post_id=post.id).first() else set()
    _boosted_ids = {post.id} if db.query(Boost).filter_by(user_id=user.id, post_id=post.id).first() else set()
    _bookmarked_ids = {post.id} if db.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first() else set()
    return _status_json(post, db, viewer=user, _liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids)


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/reactions  (Glitch-soc)
# ---------------------------------------------------------------------------
@router.get("/statuses/{status_id}/reactions")
def list_reactions(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _maybe_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    reaction_rows = db.query(
        Like.reaction, sqlfunc.count(Like.id), sqlfunc.min(Like.user_id)
    ).filter(Like.post_id == post.id).group_by(Like.reaction).order_by(sqlfunc.min(Like.id)).all()

    result = []
    for react, cnt, first_user_id in reaction_rows:
        name = react or "★"
        first_user = db.query(User).filter_by(id=first_user_id).first()
        result.append({
            "name": name,
            "count": cnt,
            "me": user is not None and db.query(Like).filter_by(user_id=user.id, post_id=post.id, reaction=react).first() is not None,
            "account": _account_json(first_user, db, viewer=user) if first_user else None,
        })
    return result


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/mute
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/mute")
def mute_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unmute
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/unmute")
def unmute_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/pin
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/pin")
def pin_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.author_id != user.id:
        raise HTTPException(status_code=404, detail="Record not found")
    pinned = list(user.pinned_posts or [])
    if post.id not in pinned:
        if len(pinned) >= 5:
            raise HTTPException(status_code=422, detail="Maximum of 5 pinned posts")
        pinned.append(post.id)
        db.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
    post.is_pinned = True
    db.commit()
    threading.Thread(target=_broadcast_update_actor, args=(user,), daemon=True).start()
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# POST /api/v1/statuses/:id/unpin
# ---------------------------------------------------------------------------
@router.post("/statuses/{status_id}/unpin")
def unpin_status(status_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.author_id != user.id:
        raise HTTPException(status_code=404, detail="Record not found")
    pinned = list(user.pinned_posts or [])
    if post.id in pinned:
        pinned.remove(post.id)
        db.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
    post.is_pinned = False
    db.commit()
    threading.Thread(target=_broadcast_update_actor, args=(user,), daemon=True).start()
    return _status_json(post, db, viewer=user)


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/reblogged_by
# ---------------------------------------------------------------------------
@router.get("/statuses/{status_id}/reblogged_by")
def reblogged_by(
    status_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=80),
):
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    q = db.query(Boost).filter(Boost.post_id == post.id)
    if max_id:
        q = q.filter(Boost.id < int(max_id))
    boosts = q.order_by(Boost.id.desc()).limit(limit).all()

    viewer = _maybe_bearer(request, db)
    return [_account_json(b.user, db, viewer) for b in boosts]


# ---------------------------------------------------------------------------
# GET /api/v1/statuses/:id/favourited_by
# ---------------------------------------------------------------------------
@router.get("/statuses/{status_id}/favourited_by")
def favourited_by(
    status_id: str,
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=40, le=80),
):
    post = db.query(Post).filter_by(id=int(status_id)).first()
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail="Record not found")

    q = db.query(Like).filter(Like.post_id == post.id)
    if max_id:
        q = q.filter(Like.id < int(max_id))
    likes = q.order_by(Like.id.desc()).limit(limit).all()

    viewer = _maybe_bearer(request, db)
    return [_account_json(l.user, db, viewer) for l in likes]


# ---------------------------------------------------------------------------
# GET /api/v1/notifications
# ---------------------------------------------------------------------------
@router.get("/notifications")
def list_notifications(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=100),
    types: list[str] = Query(default=[]),
    exclude_types: list[str] = Query(default=[]),
):
    user = _require_bearer(request, db)

    q = db.query(Notification).filter(Notification.user_id == user.id)

    type_map = {
        "follow": "follow",
        "follow_request": "follow_request",
        "mention": "mention",
        "reblog": "boost",
        "favourite": "like",
        "poll": "poll",
        "status": "status",
    }
    if types:
        mapped = [type_map.get(t, t) for t in types]
        q = q.filter(Notification.notification_type.in_(mapped))
    elif exclude_types:
        mapped = [type_map.get(t, t) for t in exclude_types]
        q = q.filter(~Notification.notification_type.in_(mapped))

    if max_id:
        q = q.filter(Notification.id < int(max_id))
    if since_id:
        q = q.filter(Notification.id > int(since_id))
    if min_id:
        q = q.filter(Notification.id > int(min_id))

    notifs = q.order_by(Notification.id.desc()).limit(limit).all()

    _NOTIF_TYPE_MAP_RESPONSE = {
        "like": "favourite",
        "reply": "mention",
        "boost": "reblog",
        "follow": "follow",
        "follow_request": "follow_request",
        "poll": "poll",
        "status": "status",
        "mention": "mention",
    }

    result = []
    for n in notifs:
        item = {
            "id": str(n.id),
            "type": _NOTIF_TYPE_MAP_RESPONSE.get(n.notification_type, n.notification_type),
            "created_at": _ap_datetime(n.created_at),
            "account": _account_json(n.from_user, db, viewer=user) if n.from_user else _account_json(user, db),
        }
        if n.post and not n.post.is_deleted:
            item["status"] = _status_json(n.post, db, viewer=user)
        else:
            item["status"] = None
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# POST /api/v1/notifications/:id/dismiss
# ---------------------------------------------------------------------------
@router.post("/notifications/{notification_id}/dismiss")
def dismiss_notification(notification_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    n = db.query(Notification).filter_by(id=int(notification_id), user_id=user.id).first()
    if n:
        n.is_read = True
        db.commit()
    return {}


# ---------------------------------------------------------------------------
# POST /api/v1/notifications/clear
# ---------------------------------------------------------------------------
@router.post("/notifications/clear")
def clear_notifications(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    db.query(Notification).filter(Notification.user_id == user.id).update({"is_read": True})
    db.commit()
    return {}


# ---------------------------------------------------------------------------
# GET /api/v1/notifications/types
# ---------------------------------------------------------------------------
@router.get("/notifications/types")
def notification_types():
    return {
        "follow": "follow",
        "follow_request": "follow_request",
        "mention": "mention",
        "reblog": "reblog",
        "favourite": "favourite",
        "poll": "poll",
        "status": "status",
        "move": "move",
        "report": "report",
    }


# ---------------------------------------------------------------------------
# GET /api/v2/search
# ---------------------------------------------------------------------------
@router.get("/search")
def search_v2(
    request: Request,
    db: SASession = Depends(get_db),
    q: str = "",
    type: str = "",
    limit: int = Query(default=20, le=80),
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
            User.is_remote == False,
            or_(
                User.username.ilike(f"%{query_lower}%"),
                User.display_name.ilike(f"%{query_lower}%"),
            )
        ).limit(limit).all()
        result["accounts"] = [_account_json(u, db, viewer) for u in users]

    if not type or type == "statuses":
        posts = db.query(Post).filter(
            Post.is_deleted == False,
            Post.visibility == "public",
            Post.content.ilike(f"%{query_lower}%"),
        ).order_by(Post.id.desc()).limit(limit).all()
        result["statuses"] = [_status_json(p, db, viewer) for p in posts if _status_json(p, db, viewer)]

    if not type or type == "hashtags":
        tags = db.query(Tag).filter(
            Tag.name.ilike(f"%{query_lower}%")
        ).limit(limit).all()
        result["hashtags"] = [
            {"name": t.display_name or t.name, "url": f"{BASE_URL}/explore?q=%23{t.display_name or t.name}"}
            for t in tags
        ]

    return result


# ---------------------------------------------------------------------------
# GET /api/v1/custom_emojis
# ---------------------------------------------------------------------------
@router.get("/custom_emojis")
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
            "aliases": e.aliases or [],
        }
        for e in emojis
    ]


# ---------------------------------------------------------------------------
# POST /api/v1/media
# ---------------------------------------------------------------------------
@router.post("/media")
async def upload_media(
    request: Request,
    db: SASession = Depends(get_db),
    file: UploadFile = File(...),
    description: str = Form(""),
    focus: str = Form(""),
):
    user = _require_bearer(request, db)

    import os
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "media")
    os.makedirs(upload_dir, exist_ok=True)

    ext = os.path.splitext(file.filename or "upload")[1] or ".bin"
    filename = f"{secrets.token_urlsafe(16)}{ext}"
    filepath = os.path.join(upload_dir, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    media_type = "image"
    if file.content_type and file.content_type.startswith("video"):
        media_type = "video"
    elif file.content_type and file.content_type.startswith("audio"):
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


# ---------------------------------------------------------------------------
# GET /api/v1/instance
# ---------------------------------------------------------------------------
@router.get("/instance")
def mastodon_instance(db: SASession = Depends(get_db)):
    settings = ServerSetting.get(db)
    user_count = db.query(sqlfunc.count(User.id)).filter(User.is_remote == False).scalar() or 0
    status_count = db.query(sqlfunc.count(Post.id)).filter(Post.is_deleted == False).scalar() or 0
    return {
        "uri": DOMAIN,
        "title": settings.server_name or "WRIT",
        "description": settings.server_description or "",
        "short_description": settings.server_description or "",
        "email": "",
        "version": "4.3.0 (compatible; WRIT)",
        "languages": ["ko"],
        "urls": {
            "streaming_api": f"wss://{DOMAIN}/api/v1/streaming",
        },
        "stats": {
            "user_count": user_count,
            "status_count": status_count,
            "domain_count": 0,
        },
        "thumbnail": settings.logo or "",
        "registrations": True,
        "approval_required": False,
        "invites_enabled": False,
        "configuration": {
            "urls": {
                "accounts": f"{BASE_URL}/authorize_fetch",
            },
            "accounts": {
                "max_featured_tags": 10,
            },
            "statuses": {
                "max_characters": MAX_POST_LENGTH,
                "max_media_attachments": 4,
                "characters_reserved_per_url": 23,
            },
            "media_attachments": {
                "supported_file_types": [
                    "image/jpeg", "image/png", "image/gif", "image/webp",
                    "video/webm", "video/mp4", "video/quicktime",
                    "audio/mpeg", "audio/ogg",
                ],
                "image_size_limit": 10485760,
                "image_matrix_limit": 4096,
                "video_size_limit": 41943040,
                "video_frame_rate_limit": 60,
                "video_matrix_limit": 2304,
            },
            "polls": {
                "max_options": 4,
                "max_characters_per_option": 50,
                "min_expiration": 300,
                "max_expiration": 2629746,
            },
            "reactions": {
                "max_reactions": 10,
            },
        },
        "rules": [],
    }


# ---------------------------------------------------------------------------
# GET /api/v1/instance/peers (stub)
# ---------------------------------------------------------------------------
@router.get("/instance/peers")
def instance_peers():
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/instance/trends (stub)
# ---------------------------------------------------------------------------
@router.get("/instance/trends")
def instance_trends(db: SASession = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.id.desc()).limit(10).all()
    return [
        {"name": t.display_name or t.name, "url": f"{BASE_URL}/explore?q=%23{t.display_name or t.name}"}
        for t in tags
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/instance/rules
# ---------------------------------------------------------------------------
@router.get("/instance/rules")
def instance_rules():
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/filters (stub)
# ---------------------------------------------------------------------------
@router.get("/filters")
def list_filters(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# POST /api/v1/filters (stub)
# ---------------------------------------------------------------------------
@router.post("/filters")
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
# GET /api/v1/preferences
# ---------------------------------------------------------------------------
@router.get("/preferences")
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
@router.get("/follow_requests")
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
@router.get("/blocks")
def list_blocks(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/mutes (stub)
# ---------------------------------------------------------------------------
@router.get("/mutes")
def list_mutes(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/bookmarks
# ---------------------------------------------------------------------------
@router.get("/bookmarks")
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
        Like.post_id.in_([b.post_id for b in bookmarks])
    ).all()) if bookmarks else set()
    _boosted_ids = set(r[0] for r in db.query(Boost.post_id).filter(
        Boost.user_id == user.id,
        Boost.post_id.in_([b.post_id for b in bookmarks])
    ).all()) if bookmarks else set()

    result = []
    for bm in bookmarks:
        if bm.post and not bm.post.is_deleted:
            s = _status_json(bm.post, db, viewer=user, _liked_ids=_liked_ids,
                             _boosted_ids=_boosted_ids, _bookmarked_ids={bm.post_id})
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/favourites
# ---------------------------------------------------------------------------
@router.get("/favourites")
def list_favourites(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=80),
):
    user = _require_bearer(request, db)
    q = db.query(Like).filter(Like.user_id == user.id)

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

    result = []
    for like in likes:
        if like.post and not like.post.is_deleted:
            s = _status_json(like.post, db, viewer=user, _liked_ids={like.post_id},
                             _boosted_ids=_boosted_ids)
            if s:
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/lists (stub)
# ---------------------------------------------------------------------------
@router.get("/lists")
def list_lists(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/suggestions (stub)
# ---------------------------------------------------------------------------
@router.get("/suggestions")
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
@router.get("/tags")
def list_tags(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/featured_tags (stub)
# ---------------------------------------------------------------------------
@router.get("/featured_tags")
def featured_tags(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/domain_blocks (stub)
# ---------------------------------------------------------------------------
@router.get("/domain_blocks")
def domain_blocks(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/endorsements (stub)
# ---------------------------------------------------------------------------
@router.get("/endorsements")
def endorsements(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/markers (stub)
# ---------------------------------------------------------------------------
@router.get("/markers")
def get_markers(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# POST /api/v1/markers (stub)
# ---------------------------------------------------------------------------
@router.post("/markers")
async def save_markers(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# POST /api/v1/push/subscription (stub)
# ---------------------------------------------------------------------------
@router.post("/push/subscription")
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
@router.get("/push/subscription")
def get_push_subscription(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# DELETE /api/v1/push/subscription (stub)
# ---------------------------------------------------------------------------
@router.delete("/push/subscription")
def delete_push_subscription(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# PUT /api/v1/push/subscription (stub)
# ---------------------------------------------------------------------------
@router.put("/push/subscription")
async def update_push_subscription(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return {}


# ---------------------------------------------------------------------------
# GET /api/v1/announcements (stub)
# ---------------------------------------------------------------------------
@router.get("/announcements")
def list_announcements(request: Request, db: SASession = Depends(get_db)):
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/trends (stub)
# ---------------------------------------------------------------------------
@router.get("/trends")
def get_trends(db: SASession = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.id.desc()).limit(10).all()
    return [
        {"name": t.display_name or t.name, "url": f"{BASE_URL}/explore?q=%23{t.display_name or t.name}", "history": []}
        for t in tags
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/trends/tags (stub)
# ---------------------------------------------------------------------------
@router.get("/trends/tags")
def get_trending_tags(db: SASession = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.id.desc()).limit(10).all()
    return [
        {"name": t.display_name or t.name, "url": f"{BASE_URL}/explore?q=%23{t.display_name or t.name}", "history": []}
        for t in tags
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/trends/statuses (stub)
# ---------------------------------------------------------------------------
@router.get("/trends/statuses")
def get_trending_statuses(
    request: Request,
    db: SASession = Depends(get_db),
    limit: int = Query(default=20, le=80),
):
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/directory
# ---------------------------------------------------------------------------
@router.get("/directory")
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
    return [_account_json(u, db, viewer) for u in users]


# ---------------------------------------------------------------------------
# GET /api/v1/conversations (stub)
# ---------------------------------------------------------------------------
@router.get("/conversations")
def list_conversations(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    limit: int = Query(default=20, le=80),
):
    user = _require_bearer(request, db)
    return []


# ---------------------------------------------------------------------------
# GET /api/v2/search (alias for v2 above — already defined)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GET /api/v1/scheduled_statuses (stub)
# ---------------------------------------------------------------------------
@router.get("/scheduled_statuses")
def list_scheduled(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    return []
