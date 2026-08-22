import base64
import datetime
import email.utils
import hashlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from fastapi import Request

from app.config.settings import BASE_URL
from app.core.activitypub._actor_resolver import _resolve_actor
from app.db.database import get_session
from app.models import Follow, User
from app.utils.crypto import verify_signature
from app.utils.http import normalize_host

logger = logging.getLogger("writ.activitypub")

# 서명 검증은 알 수 없는 액터 키를 네트워크에서 가져올 때 블로킹될 수 있다.
# async 라우트가 이 함수를 직접 호출하면 이벤트 루프 전체가 멈추므로,
# 인박스 처리 풀과 분리된 전용 풀에서 실행한다 (ap.py의 async 래퍼가 사용).
_sig_executor = ThreadPoolExecutor(
    max_workers=max(2, min(4, (os.cpu_count() or 1))),
    thread_name_prefix="ap-signature",
)

_actor_fail_cache: dict[str, float] = {}
_ACTOR_FAIL_TTL = 3600
_ACTOR_FAIL_MAX = 10000


def _record_actor_fail(actor_url: str):
    """Record a failed actor fetch, pruning expired/oldest entries when the cache grows too large."""
    _actor_fail_cache[actor_url] = time.time()
    if len(_actor_fail_cache) > _ACTOR_FAIL_MAX:
        _now = time.time()
        for _k, _ts in list(_actor_fail_cache.items()):
            if _now - _ts >= _ACTOR_FAIL_TTL:
                del _actor_fail_cache[_k]
        while len(_actor_fail_cache) > _ACTOR_FAIL_MAX:
            _oldest = min(_actor_fail_cache, key=_actor_fail_cache.get)  # type: ignore[arg-type]
            del _actor_fail_cache[_oldest]


def _local_user_by_actor_uri(session, actor_url: str):
    """Match a local user by their actor URI without scanning all local users."""
    if not actor_url or not actor_url.startswith(BASE_URL):
        return None
    rel = actor_url[len(BASE_URL):]
    if not rel.startswith("/users/"):
        return None
    username = rel[len("/users/"):].strip("/").split("/")[0]
    if not username:
        return None
    return session.query(User).filter_by(username=username, is_remote=False).first()


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
    logger.debug("[SIG] keyId=%s actor_url=%s", key_id, actor_url)
    with get_session() as s:
        remote_actor = s.query(User).filter_by(remote_url=actor_url).first()
        if not remote_actor or not remote_actor.public_key:
            remote_actor = _local_user_by_actor_uri(s, actor_url)
        if not remote_actor or not remote_actor.public_key:
            act_actor = activity.get("actor", "")
            if isinstance(act_actor, list):
                act_actor = act_actor[0]
            if act_actor:
                remote_actor = s.query(User).filter_by(remote_url=act_actor).first()
                if not remote_actor or not remote_actor.public_key:
                    remote_actor = _local_user_by_actor_uri(s, act_actor)
        if not remote_actor or not remote_actor.public_key:
            remote_actor = None
    logger.debug("[SIG] db_lookup=%s", "found" if remote_actor else "miss")

    if not remote_actor or not remote_actor.public_key:
        _fail_ts = _actor_fail_cache.get(actor_url)
        if _fail_ts and (time.time() - _fail_ts) < _ACTOR_FAIL_TTL:
            logger.debug("[SIG] skip fetch (cached fail, %ds ago) for %s", int(time.time() - _fail_ts), actor_url)
            return (False, None)
        logger.debug("[SIG] trying network fetch for %s", actor_url)
        try:
            if BASE_URL in actor_url:
                logger.debug("[SIG] skip self-fetch (%s)", BASE_URL)
            else:
                with get_session() as _s:
                    _signer = _s.query(User).filter_by(is_remote=False).first()
                remote_actor = _resolve_actor(actor_url, lightweight=True, sign_as=_signer)
                if remote_actor and remote_actor.public_key:
                    logger.debug("[SIG] resolved remote actor (id=%s)", remote_actor.id)
                else:
                    _record_actor_fail(actor_url)
                    logger.debug("[SIG] cached fail for %s", actor_url)
        except Exception:
            _record_actor_fail(actor_url)
    if not remote_actor or not remote_actor.public_key:
        return (False, None)

    activity_actor = activity.get("actor")
    if isinstance(activity_actor, list):
        activity_actor = activity_actor[0]
    signer_uri = remote_actor.actor_uri() if not remote_actor.is_remote else remote_actor.remote_url
    logger.debug("[SIG] bind_check signer_uri=%s activity_actor=%s", signer_uri, activity_actor)
    if not activity_actor:
        if body:
            logger.debug("[SIG] bind_check FAIL (no activity_actor)")
            return (False, None)
        logger.debug("[SIG] bind_check skipped (GET dereference, no activity actor)")
    elif signer_uri != activity_actor:
        # 서명자(HTTP 서명 keyId의 주인)와 activity.actor가 일치해야만 신뢰한다.
        # 예전에는 "inbox forwarding" 예외(상대방 to/cc에 서명자 도메인이 있으면 허용)가 있었는데,
        # 공격자가 to/cc에 자기 도메인을 넣으면 언제나 통과해 임의 액터(로컬 포함) 사칭이 가능했다.
        # 크로스서버 포워딩은 포기하되, 사칭 벡터를 완전히 제거한다.
        logger.debug("[SIG] bind_check FAIL (signer != actor)")
        return (False, None)
    else:
        logger.debug("[SIG] bind_check OK")

    activity_id = activity.get("id", "")
    if activity_id:
        try:
            actor_domain = urlparse(activity_actor).netloc
            id_domain = urlparse(activity_id).netloc
            if actor_domain and id_domain and actor_domain != id_domain:
                logger.debug("[SIG] domain_check FAIL (actor_domain=%s != id_domain=%s)", actor_domain, id_domain)
                return (False, None)
        except Exception:
            pass

    now = datetime.datetime.now(datetime.UTC)
    freshness_ok = False
    date_header = request.headers.get("Date", "")
    if date_header:
        try:
            date_tuple = email.utils.parsedate_tz(date_header)
            if date_tuple:
                date_dt = datetime.datetime.fromtimestamp(
                    email.utils.mktime_tz(date_tuple), tz=datetime.UTC)
                if abs((now - date_dt).total_seconds()) <= 300:
                    freshness_ok = True
                else:
                    logger.debug("[SIG] date_freshness FAIL diff=%s",
                                 abs((now - date_dt).total_seconds()))
                    return (False, None)
        except (ValueError, TypeError, OverflowError):
            logger.debug("[SIG] date_parse FAIL")
            return (False, None)
    # hs2019 `created` 파라미터: Date 대신 사용되는 신선도 기준
    created_param = params.get("created", "")
    if created_param:
        try:
            created_ts = float(created_param)
            created_dt = datetime.datetime.fromtimestamp(created_ts, tz=datetime.UTC)
            if abs((now - created_dt).total_seconds()) <= 300:
                freshness_ok = True
            else:
                logger.debug("[SIG] created_freshness FAIL diff=%s",
                             abs((now - created_dt).total_seconds()))
                return (False, None)
        except (ValueError, TypeError, OverflowError, OSError):
            logger.debug("[SIG] created_parse FAIL")
            return (False, None)
    # replay 방어: 신선도 기준(Date 또는 hs2019 created)이 전무하면 거부
    if not freshness_ok:
        logger.debug("[SIG] freshness FAIL (no Date/created)")
        return (False, None)

    path = request.url.path
    date = request.headers.get("Date", "")
    host_header = normalize_host(request)
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
    logger.debug("[SIG] verifying signature... signed_string=%r", signed_string[:200])
    ok = verify_signature(signed_string, sig_b64, remote_actor.public_key)
    logger.debug("[SIG] verify=%s", "OK" if ok else "FAIL")
    if not ok:
        logger.debug("[SIG] retrying with _resolve_actor force_refresh")
        fresh = _resolve_actor(actor_url, force_refresh=True)
        if fresh and fresh.public_key:
            ok = verify_signature(signed_string, sig_b64, fresh.public_key)  # type: ignore[arg-type]
            logger.debug("[SIG] retry verify=%s", "OK" if ok else "FAIL")
            return (ok, fresh if ok else None)
    return (ok, remote_actor if ok else None)


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


def _validate_inbox_activity(activity: dict):
    """Validate common inbox activity fields.

    Returns (status_code, message) on failure, or None when the activity is well-formed.
    """
    atype = activity.get("type")
    if not atype:
        return (400, "Missing activity type")
    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    if not actor_url:
        return (400, "Missing actor")
    if atype in ("Create", "Update", "Like", "Announce", "Undo") and not activity.get("object"):
        return (400, "Missing object")
    if atype == "Undo":
        object_data = activity.get("object", {})
        if isinstance(object_data, dict):
            obj_actor = object_data.get("actor", "")
            if isinstance(obj_actor, list):
                obj_actor = obj_actor[0]
            if obj_actor and obj_actor != actor_url:
                return (403, "Undo actor mismatch")
    return None
