import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config.settings import BASE_URL, DOMAIN, S3_ENABLED
from app.core.activitypub import (
    _ap_post_visible,
    _is_activity_processed,
    _mark_activity_processed,
    _submit_inbox,
    _validate_inbox_activity,
    get_featured,
    get_followers,
    get_following,
    get_outbox,
    verify_http_signature,
)
from app.core.rate_limit import check_burst_limit, check_daily_limit, check_rate_limit
from app.db.database import get_session
from app.models import (
    Boost,
    CustomEmoji,
    Follow,
    Like,
    Novel,
    Post,
    User,
)
from app.utils.storage import get_storage
from app.utils.to_ap_serializer import to_ap_actor, to_ap_create, to_ap_note

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# WebFinger
# ---------------------------------------------------------------------------
@router.get("/.well-known/webfinger")
def webfinger(request: Request, resource: str = ""):
    if not resource or not resource.startswith("acct:"):
        return JSONResponse({"error": "Invalid resource"}, status_code=400)

    acct = resource[5:]
    if "@" in acct:
        username, domain = acct.split("@", 1)
        if domain != DOMAIN:
            return JSONResponse({"error": "Not found"}, status_code=404)
    else:
        username = acct

    username = username.replace(f"@{DOMAIN}", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)

    return JSONResponse({
        "subject": f"acct:{username}@{DOMAIN}",
        "aliases": [
            user.actor_uri(),
        ],
        "links": [
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": user.actor_uri(),
            },
            {
                "rel": "http://webfinger.net/rel/profile-page",
                "type": "text/html",
                "href": user.actor_uri(),
            },
        ],
    }, media_type="application/jrd+json")


# ---------------------------------------------------------------------------
# Actor & Collections
# ---------------------------------------------------------------------------
def _actor_response(request: Request, user: User, redirect_url: str) -> JSONResponse | RedirectResponse:
    """Serve an actor as ActivityPub JSON or redirect browsers to the profile page.

    Shared by /users/{username} and /@{username}. The caller resolves the user
    and picks the browser redirect target.
    """
    accept = request.headers.get("Accept", "")
    wants_json = "application/activity+json" in accept or "application/ld+json" in accept
    if getattr(user, "is_deactivated", False):
        if wants_json:
            return JSONResponse({"error": "Gone"}, status_code=410)
        raise HTTPException(status_code=410, detail="Account deleted")
    if wants_json:
        return JSONResponse(content=to_ap_actor(user), media_type="application/activity+json")
    return RedirectResponse(url=redirect_url)


@router.get("/users/{username}")
def user_actor(request: Request, username: str):
    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return _actor_response(request, user, f"{BASE_URL}/@{username}")


def _check_collection_access(username: str) -> bool:
    """Check if the user exists and is not deactivated before serving collections.

    Collection functions themselves return None for missing users, but an early
    check lets us also exclude deactivated accounts and return a proper 404.
    """
    with get_session() as s:
        user = s.query(User).filter_by(username=username).first()
        return not (not user or getattr(user, 'is_deactivated', False))


@router.get("/users/{username}/outbox")
def user_outbox(username: str, page: int | None = None):
    if not _check_collection_access(username):
        raise HTTPException(status_code=404, detail="Not found")
    result = get_outbox(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@router.get("/users/{username}/followers")
def user_followers(username: str, page: int | None = None):
    if not _check_collection_access(username):
        raise HTTPException(status_code=404, detail="Not found")
    result = get_followers(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@router.get("/users/{username}/following")
def user_following(username: str, page: int | None = None):
    if not _check_collection_access(username):
        raise HTTPException(status_code=404, detail="Not found")
    result = get_following(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@router.get("/users/{username}/featured")
def user_featured(username: str, page: int | None = None):
    if not _check_collection_access(username):
        raise HTTPException(status_code=404, detail="Not found")
    result = get_featured(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------
async def _parse_inbox_body(request: Request) -> tuple[bytes, dict]:
    """Read and parse the request body, enforcing the size limit.

    Returns (raw_body, activity) so signature verification can reuse the
    exact bytes that were read.
    """
    try:
        body = await request.body()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid body") from exc
    if len(body) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Request body too large")
    try:
        return body, json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc


def _inbox_rate_guard(request: Request, actor_url: str):
    """Apply daily/rate/burst limits keyed by actor and client IP."""
    client_ip = request.client.host if request.client else ""
    actor_key = f"actor:{actor_url}" if actor_url else ""
    ip_key = f"ip:{client_ip}" if client_ip else ""
    daily_key = f"daily:{actor_key or ip_key}"
    if not check_daily_limit(daily_key):
        raise HTTPException(status_code=429, detail="Daily limit exceeded")
    for rk in [actor_key, ip_key]:
        if rk and (not check_rate_limit(rk) or not check_burst_limit(rk)):
            raise HTTPException(status_code=429, detail="Too many requests")


@router.post("/inbox")
async def shared_inbox(request: Request):
    body, activity = await _parse_inbox_body(request)
    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    _inbox_rate_guard(request, actor_url)

    ok, _remote_actor = verify_http_signature(request, body, activity)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=401)
    err = _validate_inbox_activity(activity)
    if err:
        return JSONResponse({"status": "error", "message": err[1]}, status_code=err[0])

    activity_id = activity.get("id", "")
    if _is_activity_processed(activity_id):
        return JSONResponse({"status": 200, "message": "Already processed"})
    _mark_activity_processed(activity_id)

    status_code, message = await _submit_inbox(activity)
    return JSONResponse({"status": status_code, "message": message}, status_code=200)


@router.post("/users/{username}/inbox")
async def user_inbox(request: Request, username: str):
    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

    body, activity = await _parse_inbox_body(request)
    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]

    activity_id = activity.get("id", "")
    if _is_activity_processed(activity_id):
        return JSONResponse({"status": "ok", "message": "Already processed"}, status_code=200)
    _inbox_rate_guard(request, actor_url)

    to_list = activity.get("to", [])
    if isinstance(to_list, str):
        to_list = [to_list]
    cc_list = activity.get("cc", [])
    if isinstance(cc_list, str):
        cc_list = [cc_list]
    all_audiences = to_list + cc_list
    user_uri = user.actor_uri()
    atype = activity.get("type")
    if atype in ("Follow", "Delete", "Reject", "Accept", "Undo", "Vote", "Like", "Announce", "Block", "Flag"):
        pass
    elif user_uri not in all_audiences and f"{user_uri}/followers" not in all_audiences:
        return JSONResponse({"status": "error", "message": "Not addressed to this user"}, status_code=403)

    request.state.sign_as_user = user
    ok, _remote_actor = verify_http_signature(request, body, activity)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=401)

    err = _validate_inbox_activity(activity)
    if err:
        return JSONResponse({"status": "error", "message": err[1]}, status_code=err[0])

    atype = activity.get("type")
    if atype == "Follow":
        target = activity.get("object", "")
        if isinstance(target, dict):
            target = target.get("id", "")
        if isinstance(target, str) and target != user.actor_uri():
            return JSONResponse({"status": "error", "message": "Follow target mismatch"}, status_code=403)

    _mark_activity_processed(activity_id)

    status_code, message = await _submit_inbox(activity)
    return JSONResponse({"status": status_code, "message": message}, status_code=200)


# ---------------------------------------------------------------------------
# Activity dereference endpoints
# ---------------------------------------------------------------------------
@router.get("/activities/follow/{follow_uuid}")
def get_follow_activity(request: Request, follow_uuid: str):
    accept = request.headers.get("Accept", "")
    if "application/activity+json" not in accept:
        return JSONResponse({"error": "Not found"}, status_code=404)
    with get_session() as session:
        activity_id = f"{BASE_URL}/activities/follow/{follow_uuid}"
        follow = session.query(Follow).filter_by(activity_id=activity_id).first()
        if not follow:
            raise HTTPException(status_code=404, detail="Not found")
        follower = session.query(User).get(follow.follower_id)
        following = session.query(User).get(follow.following_id)
        if not follower or not following:
            raise HTTPException(status_code=404, detail="Not found")
        obj = following.actor_uri()
        activity = {
            "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
            "id": activity_id,
            "type": "Follow",
            "actor": follower.actor_uri(),
            "object": obj,
            "to": [obj],
        }
        return JSONResponse(content=activity, media_type="application/activity+json")

@router.get("/activities/create/{post_id}")
def get_create_activity(request: Request, post_id: int):
    accept = request.headers.get("Accept", "")
    if "application/activity+json" not in accept:
        return JSONResponse({"error": "Not found"}, status_code=404)
    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Not found")
        if not _ap_post_visible(post, request, session):
            raise HTTPException(status_code=404, detail="Not found")
        return JSONResponse(content=to_ap_create(post),
                            media_type="application/activity+json")


@router.get("/posts/{post_id}")
def get_post(request: Request, post_id: int):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Not found")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            if not _ap_post_visible(post, request, session):
                raise HTTPException(status_code=404, detail="Not found")
            return JSONResponse(content=to_ap_note(post),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"/post/{post_id}")


@router.get("/@{username}")
def get_user_by_handle(request: Request, username: str):
    with get_session() as session:
        if "@" in username:
            user = session.query(User).filter_by(username=username, is_remote=True).first()
        else:
            user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        return _actor_response(request, user, f"{BASE_URL}/profile/{username}")


@router.get("/likes/{like_uuid}")
def get_like(like_uuid: str):
    """Return a Like activity (dereferenceable URI)."""
    ap_id = f"{BASE_URL}/likes/{like_uuid}"
    with get_session() as s:
        like = s.query(Like).filter_by(ap_id=ap_id).first()
        if not like:
            return JSONResponse({"error": "Not found"}, status_code=404)
        post = like.post
        actor = s.query(User).get(like.user_id)
        if not post or not actor:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse({
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": ap_id,
            "type": "Like",
            "actor": actor.actor_uri(),
            "object": post.ap_id,
            "_misskey_reaction": like.reaction or "★",
        }, media_type="application/activity+json")

@router.get("/emojis/{keyword}")
def get_emoji(keyword: str):
    """Return an Emoji activity (dereferenceable URI)."""
    ap_id = f"{BASE_URL}/emojis/{keyword}"
    with get_session() as s:
        emoji = s.query(CustomEmoji).filter_by(keyword=keyword).first()
        if not emoji:
            return JSONResponse({"error": "Not found"}, status_code=404)
        sub = "remote" if emoji.domain or emoji.category == "remote" else "local"
        if S3_ENABLED:
            try:
                storage = get_storage()
                url = storage.url(f"emojis/{sub}/{emoji.file_name}")
            except Exception:
                url = f"{BASE_URL}/emojis/{sub}/{emoji.file_name}"
        else:
            url = f"{BASE_URL}/emojis/{sub}/{emoji.file_name}"
        ext = emoji.file_name.rsplit(".", 1)[-1].lower() if "." in emoji.file_name else "png"
        mt = f"image/{ext}" if ext in ("png", "jpg", "jpeg", "gif", "webp", "svg") else "image/png"
        return JSONResponse({
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": ap_id,
            "type": "Emoji",
            "name": f":{keyword}:",
            "icon": {
                "type": "Image",
                "mediaType": mt,
                "url": url,
            },
        }, media_type="application/activity+json")


@router.get("/boosts/{boost_uuid}")
def get_boost(boost_uuid: str):
    """Return an Announce activity (dereferenceable URI)."""
    ap_id = f"{BASE_URL}/boosts/{boost_uuid}"
    with get_session() as s:
        boost = s.query(Boost).filter_by(ap_id=ap_id).first()
        if not boost:
            return JSONResponse({"error": "Not found"}, status_code=404)
        post = boost.post
        actor = s.query(User).get(boost.user_id)
        if not post or not actor:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse({
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": ap_id,
            "type": "Announce",
            "actor": actor.actor_uri(),
            "object": post.ap_id,
        }, media_type="application/activity+json")

@router.get("/@{username}/{number}")
def get_post_by_handle(request: Request, username: str, number: str):
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        post = session.query(Post).filter_by(author_id=user.id, number=number).first()
        if not post:
            raise HTTPException(status_code=404, detail="Not found")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            if post.is_deleted:
                return JSONResponse(content=to_ap_note(post),
                                    media_type="application/activity+json")
            if not _ap_post_visible(post, request, session):
                raise HTTPException(status_code=404, detail="Not found")
            return JSONResponse(content=to_ap_note(post),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"/post/{post.id}")


@router.get("/@{username}/series/{number}")
def get_series_by_handle(request: Request, username: str, number: str):
    request.headers.get("Accept", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        novel = session.query(Novel).filter_by(author_id=user.id, number=number).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Not found")

        return RedirectResponse(url=f"/series/{novel.id}")
