import asyncio
import base64
import datetime
import email.utils
import hashlib
import json
import logging
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from app.config.settings import SECRET_KEY, BASE_URL, DOMAIN, S3_ENABLED
from app.core.activitypub import (
    get_outbox, get_followers, get_following, handle_inbox,
    _resolve_actor, get_featured,
)
from app.core.rate_limit import check_rate_limit, check_burst_limit, check_daily_limit
from app.db.database import get_session
from app.models import (
    User, Follow, Post, Novel, ProcessedActivity, Like, Boost, CustomEmoji,
)
from app.utils.to_ap_serializer import to_ap_note, to_ap_create, to_ap_actor
from app.utils.crypto import verify_signature, sign_string, get_private_key
from app.utils.storage import get_storage

logger = logging.getLogger(__name__)

_actor_fail_cache: dict[str, float] = {}
_ACTOR_FAIL_TTL = 3600

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
@router.get("/users/{username}")
def user_actor(request: Request, username: str):
    accept = request.headers.get("Accept", "")

    session = get_session()
    try:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if getattr(user, 'is_deactivated', False):
            if "application/activity+json" in accept or "application/ld+json" in accept:
                return JSONResponse({"error": "Gone"}, status_code=410)
            raise HTTPException(status_code=410, detail="Account deleted")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            return JSONResponse(content=to_ap_actor(user),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"{BASE_URL}/users/{username}")
    finally:
        session.close()


def _check_collection_access(username: str, request: Request) -> bool:
    """Check if the requester can view this user's ActivityPub collections."""
    with get_session() as s:
        user = s.query(User).filter_by(username=username).first()
        if not user:
            return False
        return True


@router.get("/users/{username}/outbox")
def user_outbox(request: Request, username: str, page: int = None):
    if not _check_collection_access(username, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = get_outbox(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@router.get("/users/{username}/followers")
def user_followers(request: Request, username: str, page: int = None):
    if not _check_collection_access(username, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = get_followers(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@router.get("/users/{username}/following")
def user_following(request: Request, username: str, page: int = None):
    if not _check_collection_access(username, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = get_following(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


@router.get("/users/{username}/featured")
def user_featured(request: Request, username: str, page: int = None):
    if not _check_collection_access(username, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = get_featured(username, page)
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=result, media_type="application/activity+json")


# ---------------------------------------------------------------------------
# HTTP Signature verification
# ---------------------------------------------------------------------------
def _ap_post_visible(post, request, session):
    """Check if an AP post is visible to the requester."""
    v = post.visibility or "public"
    if v in ("public", "unlisted", "home"):
        return True
    accept = request.headers.get("Accept", "")
    if "application/activity+json" not in accept and "application/ld+json" not in accept:
        return True
    ok, remote_actor = verify_http_signature(request, b"", {})
    if not ok or not remote_actor:
        return False
    if v == "followers":
        if post.mentioned_user_ids and remote_actor.id in post.mentioned_user_ids:
            return True
        return session.query(Follow).filter_by(
            follower_id=remote_actor.id, following_id=post.author_id, accepted=True
        ).first() is not None
    if v == "mention":
        return post.mentioned_user_ids and remote_actor.id in post.mentioned_user_ids
    return False


def verify_http_signature(request: Request, body: bytes, activity: dict) -> tuple[bool, object]:
    """Verify HTTP signature.
    Returns (ok, remote_actor_or_None).
    """
    signature_header = request.headers.get("Signature", "")
    if not signature_header:
        return (False, None)
    params = {}
    for part in signature_header.split(","):
        if "=" in part:
            key, _, val = part.partition("=")
            params[key.strip()] = val.strip().strip('"')
    key_id = params.get("keyId", "")
    headers_str = params.get("headers", "")
    sig_b64 = params.get("signature", "")
    if not key_id or not sig_b64:
        return (False, None)

    if body:
        digest_header = request.headers.get("Digest", "")
        if not digest_header:
            return (False, None)
        expected_b64 = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
        expected_hex = "SHA-256=" + hashlib.sha256(body).hexdigest()
        if digest_header not in (expected_b64, expected_hex):
            return (False, None)

    actor_url = key_id.split("#")[0] if "#" in key_id else key_id
    print(f"[SIG] keyId={key_id} actor_url={actor_url}", flush=True)
    with get_session() as s:
        remote_actor = s.query(User).filter_by(remote_url=actor_url).first()
        if not remote_actor or not remote_actor.public_key:
            for _u in s.query(User).filter_by(is_remote=False).all():
                if _u.actor_uri() == actor_url:
                    remote_actor = _u
                    break
        if not remote_actor or not remote_actor.public_key:
            act_actor = activity.get("actor", "")
            if isinstance(act_actor, list):
                act_actor = act_actor[0]
            if act_actor:
                remote_actor = s.query(User).filter_by(remote_url=act_actor).first()
                if not remote_actor or not remote_actor.public_key:
                    for _u in s.query(User).filter_by(is_remote=False).all():
                        if _u.actor_uri() == act_actor:
                            remote_actor = _u
                            break
        if not remote_actor or not remote_actor.public_key:
            remote_actor = None
    print(f"[SIG] db_lookup={'found' if remote_actor else 'miss'}", flush=True)

    if not remote_actor or not remote_actor.public_key:
        _fail_ts = _actor_fail_cache.get(actor_url)
        if _fail_ts and (time.time() - _fail_ts) < _ACTOR_FAIL_TTL:
            print(f"[SIG] skip fetch (cached fail, {int(time.time() - _fail_ts)}s ago) for {actor_url}", flush=True)
            return (False, None)
        print(f"[SIG] trying network fetch for {actor_url}", flush=True)
        try:
            if BASE_URL in actor_url:
                print(f"[SIG] skip self-fetch ({BASE_URL})", flush=True)
            else:
                _parsed = urlparse(actor_url)
                _date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                _created = int(time.time())
                _ss = f"(request-target): get {_parsed.path}\nhost: {_parsed.netloc}\ndate: {_date}\n(created): {_created}"
                _headers = {"Accept": "application/activity+json", "Date": _date, "Host": _parsed.netloc}
                with get_session() as _s:
                    _signer = _s.query(User).filter_by(is_remote=False).first()
                    if _signer:
                        _priv = get_private_key(_signer, SECRET_KEY)
                        _sig = sign_string(_ss, _priv)
                        _headers["Signature"] = f'keyId="{_signer.actor_uri()}#main-key",algorithm="hs2019",created="{_created}",headers="(request-target) host date (created)",signature="{_sig}"'
                _resp = httpx.get(actor_url, headers=_headers, timeout=10, follow_redirects=True)
                print(f"[SIG] fetch status={_resp.status_code}", flush=True)
                if _resp.status_code == 200:
                    _data = _resp.json()
                    _pubkey = _data.get("publicKey", {}).get("publicKeyPem", "") if isinstance(_data, dict) else ""
                    print(f"[SIG] pubkey_len={len(_pubkey)}", flush=True)
                    if _pubkey:
                        class _Actor:
                            public_key = _pubkey
                            remote_url = actor_url
                            is_remote = True
                            @staticmethod
                            def actor_uri(): return actor_url
                        remote_actor = _Actor()
                        print(f"[SIG] using inline _Actor (pubkey_len={len(_pubkey)})", flush=True)
                else:
                    _actor_fail_cache[actor_url] = time.time()
                    print(f"[SIG] cached fail for {actor_url} (status={_resp.status_code})", flush=True)
        except Exception:
            pass
    if not remote_actor or not remote_actor.public_key:
        return (False, None)

    activity_actor = activity.get("actor")
    if isinstance(activity_actor, list):
        activity_actor = activity_actor[0]
    signer_uri = remote_actor.actor_uri() if not remote_actor.is_remote else remote_actor.remote_url
    print(f"[SIG] bind_check signer_uri={signer_uri} activity_actor={activity_actor}", flush=True)
    if not activity_actor:
        print(f"[SIG] bind_check FAIL (no activity_actor)", flush=True)
        return (False, None)
    if signer_uri != activity_actor:
        try:
            signer_domain = urlparse(signer_uri).netloc
            actor_domain = urlparse(activity_actor).netloc
            if signer_domain and actor_domain and signer_domain != actor_domain:
                audience = []
                for key in ("to", "cc", "bto", "bcc"):
                    val = activity.get(key)
                    if val:
                        if isinstance(val, list):
                            audience.extend(val)
                        else:
                            audience.append(val)
                forwarded = any(
                    urlparse(a).netloc == signer_domain
                    for a in audience if isinstance(a, str) and a.startswith("http")
                )
                if forwarded:
                    print(f"[SIG] bind_check OK (inbox forwarding from {signer_domain})", flush=True)
                else:
                    print(f"[SIG] bind_check FAIL (signer != actor, no forwarding auth)", flush=True)
                    return (False, None)
            else:
                print(f"[SIG] bind_check FAIL (signer != actor)", flush=True)
                return (False, None)
        except Exception:
            print(f"[SIG] bind_check FAIL (signer != actor)", flush=True)
            return (False, None)
    print(f"[SIG] bind_check OK", flush=True)

    activity_id = activity.get("id", "")
    if activity_id:
        try:
            actor_domain = urlparse(activity_actor).netloc
            id_domain = urlparse(activity_id).netloc
            if actor_domain and id_domain and actor_domain != id_domain:
                print(f"[SIG] domain_check FAIL (actor_domain={actor_domain} != id_domain={id_domain})", flush=True)
                return (False, None)
        except Exception:
            pass

    date_header = request.headers.get("Date", "")
    if date_header:
        try:
            date_tuple = email.utils.parsedate_tz(date_header)
            if date_tuple:
                date_dt = datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple), tz=datetime.timezone.utc)
                now = datetime.datetime.now(datetime.timezone.utc)
                diff = abs((now - date_dt).total_seconds())
                if diff > 300:
                    print(f"[SIG] date_freshness FAIL diff={diff}", flush=True)
                    return (False, None)
        except (ValueError, TypeError, OverflowError):
            print(f"[SIG] date_parse FAIL", flush=True)
            return (False, None)

    path = request.url.path
    date = request.headers.get("Date", "")
    host_header = request.headers.get("Host", "")
    if host_header in ("api:8000", "localhost:8000") or host_header.startswith("172."):
        host_header = DOMAIN
    digest_val = request.headers.get("Digest", "")
    signed_parts = {
        "(request-target)": f"post {path}",
        "host": host_header,
        "date": date,
        "digest": digest_val,
    }
    method = request.method.lower()
    created_param = params.get("created", "")
    signed_lines = []
    for h in headers_str.split():
        h = h.strip()
        if h == "(request-target)":
            signed_lines.append(f"(request-target): {method} {path}")
        elif h in ("(request-created)", "(created)"):
            signed_lines.append(f"{h}: {created_param}")
        elif h in signed_parts:
            signed_lines.append(f"{h}: {signed_parts[h]}")
        else:
            val = request.headers.get(h, "")
            signed_lines.append(f"{h}: {val}")
    signed_string = "\n".join(signed_lines)
    print(f"[SIG] verifying signature... signed_string={repr(signed_string)[:200]}", flush=True)
    ok = verify_signature(signed_string, sig_b64, remote_actor.public_key)
    print(f"[SIG] verify={'OK' if ok else 'FAIL'}", flush=True)
    if not ok:
        print(f"[SIG] retrying with _resolve_actor force_refresh", flush=True)
        fresh = _resolve_actor(actor_url, force_refresh=True)
        if fresh and fresh.public_key:
            ok = verify_signature(signed_string, sig_b64, fresh.public_key)
            print(f"[SIG] retry verify={'OK' if ok else 'FAIL'}", flush=True)
            return (ok, fresh if ok else None)
    return (ok, remote_actor if ok else None)


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------
@router.post("/inbox")
async def shared_inbox(request: Request):
    try:
        body = await request.body()
    except Exception:
        return {"ok": False}
    if len(body) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Request body too large")
    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    client_ip = request.client.host if request.client else ""
    rate_key = f"inbox:{actor_url or client_ip}"
    if not check_rate_limit(rate_key):
        return JSONResponse({"status": "error", "message": "Too many requests"}, status_code=429)
    ok, remote_actor = verify_http_signature(request, body, activity)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=401)
    activity_id = activity.get("id", "")
    if activity_id:
        with get_session() as s:
            already = s.query(ProcessedActivity).filter_by(id=activity_id).first()
            if already:
                return JSONResponse({"status": 200, "message": "Already processed"})
            s.add(ProcessedActivity(id=activity_id))
            s.commit()
    loop = asyncio.get_event_loop()
    status_code, message = await loop.run_in_executor(None, handle_inbox, activity)
    return JSONResponse({"status": status_code, "message": message}, status_code=200)


@router.post("/users/{username}/inbox")
async def user_inbox(request: Request, username: str):
    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Request body too large")
    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]

    activity_id = activity.get("id", "")
    if activity_id:
        with get_session() as s:
            already = s.query(ProcessedActivity).filter_by(id=activity_id).first()
            if already:
                return JSONResponse({"status": "ok", "message": "Already processed"}, status_code=200)

    client_ip = request.client.host if request.client else ""
    actor_key = f"actor:{actor_url}" if actor_url else ""
    ip_key = f"ip:{client_ip}" if client_ip else ""
    daily_key = f"daily:{actor_key or ip_key}"
    if not check_daily_limit(daily_key):
        return JSONResponse({"status": "error", "message": "Daily limit exceeded"}, status_code=429)
    for rk in [actor_key, ip_key]:
        if rk and (not check_rate_limit(rk) or not check_burst_limit(rk)):
            return JSONResponse({"status": "error", "message": "Too many requests"}, status_code=429)

    to_list = activity.get("to", [])
    if isinstance(to_list, str):
        to_list = [to_list]
    cc_list = activity.get("cc", [])
    if isinstance(cc_list, str):
        cc_list = [cc_list]
    all_audiences = to_list + cc_list
    user_uri = user.actor_uri()
    atype = activity.get("type")
    if atype in ("Follow", "Delete", "Reject", "Accept", "Undo", "Vote", "Like", "Announce", "Block"):
        pass
    elif atype == "Flag":
        pass
    elif user_uri not in all_audiences and f"{user_uri}/followers" not in all_audiences:
        return JSONResponse({"status": "error", "message": "Not addressed to this user"}, status_code=403)

    request.state.sign_as_user = user
    ok, remote_actor = verify_http_signature(request, body, activity)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=401)

    if not atype:
        return JSONResponse({"status": "error", "message": "Missing activity type"}, status_code=400)
    if not actor_url:
        return JSONResponse({"status": "error", "message": "Missing actor"}, status_code=400)
    if atype in ("Create", "Update") and not activity.get("object"):
        return JSONResponse({"status": "error", "message": "Missing object"}, status_code=400)
    if atype in ("Like", "Announce", "Undo") and not activity.get("object"):
        return JSONResponse({"status": "error", "message": "Missing object"}, status_code=400)

    if atype == "Follow":
        target = activity.get("object", "")
        if isinstance(target, dict):
            target = target.get("id", "")
        if isinstance(target, str) and target != user.actor_uri():
            return JSONResponse({"status": "error", "message": "Follow target mismatch"}, status_code=403)

    if atype in ("Like", "Announce"):
        pass
    if atype == "Undo":
        object_data = activity.get("object", {})
        if isinstance(object_data, dict):
            obj_actor = object_data.get("actor", "")
            if isinstance(obj_actor, list):
                obj_actor = obj_actor[0]
            if obj_actor and obj_actor != actor_url:
                return JSONResponse({"status": "error", "message": "Undo actor mismatch"}, status_code=403)

    if activity_id:
        with get_session() as s:
            s.add(ProcessedActivity(id=activity_id))
            s.commit()

    loop = asyncio.get_event_loop()
    status_code, message = await loop.run_in_executor(None, handle_inbox, activity)
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
        obj = following.actor_uri() if following.is_remote else following.actor_uri()
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
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        if "@" in username:
            user = session.query(User).filter_by(username=username, is_remote=True).first()
        else:
            user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        if getattr(user, 'is_deactivated', False):
            if "application/activity+json" in accept or "application/ld+json" in accept:
                return JSONResponse({"error": "Gone"}, status_code=410)
            raise HTTPException(status_code=410, detail="Account deleted")

        if "application/activity+json" in accept or "application/ld+json" in accept:
            return JSONResponse(content=to_ap_actor(user),
                                media_type="application/activity+json")

        return RedirectResponse(url=f"{BASE_URL}/profile/{username}")


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
    accept = request.headers.get("Accept", "")

    with get_session() as session:
        user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        novel = session.query(Novel).filter_by(author_id=user.id, number=number).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Not found")

        return RedirectResponse(url=f"/series/{novel.id}")
