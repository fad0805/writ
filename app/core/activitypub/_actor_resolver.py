"""Remote actor resolution.

_fetch_actor와 _fetch_post 사이에 환원 불가능한 순환 import(_resolve_actor ↔
_fetch_remote_post)가 있어 분리했다. 이 모듈은 다른 activitypub 모듈을
import하지 않는다(순수). pinned 동기화(_sync_remote_pinned_posts)는
_fetch_actor의 랩퍼가 반환된 user.pending_pinned_ap_ids로 수행한다.
"""

import datetime
import logging
import re
import time
import uuid
from urllib.parse import urlparse

from app.config.settings import BASE_URL, SECRET_KEY
from app.core.activitypub._emoji import _process_emoji_tags
from app.core.activitypub._fetch_http import _fetch_ap_json
from app.core.activitypub._media import _save_remote_avatar, _save_remote_image
from app.db.database import get_session
from app.models import User
from app.utils.crypto import encrypt_key, generate_keypair, get_private_key, sign_string
from app.utils.http import WRIT_USER_AGENT, safe_fetch, validated_get
from app.utils.urls import parse_username_from_url

logger = logging.getLogger("writ.activitypub")


def _extract_custom_fields(attachment: list) -> list:
    """Extract PropertyValue entries from remote actor attachment field."""
    fields = []
    for item in attachment:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "PropertyValue":
            continue
        name = item.get("name", "").strip()
        value = item.get("value", "")
        if not name or not value:
            continue
        # Strip HTML tags from value (Mastodon sends HTML links)
        value = re.sub(r"<[^>]*>", "", value).strip()
        fields.append({"name": name, "value": value})
    return fields


def _fetch_remote_count(collection_url: str, sign_as: User | None = None) -> int:
    """Fetch totalItems from a remote ActivityPub collection (followers/following)."""
    if not collection_url:
        return 0
    try:
        headers = {"Accept": "application/activity+json, application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\"", "User-Agent": WRIT_USER_AGENT}
        if sign_as:
            parsed = urlparse(collection_url)
            date = datetime.datetime.now(datetime.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            headers["Signature"] = f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            headers["Date"] = date
            headers["Host"] = parsed.netloc
        resp = validated_get(collection_url, headers=headers, timeout=10)
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            try:
                count = int(data.get("totalItems", 0))
            except (TypeError, ValueError):
                return 0
            # 원격 서버가 조작한 과도한 수치가 표시되지 않도록 상한을 둔다
            return max(0, min(count, 10_000_000))
    except Exception:
        pass
    return 0


def _fetch_remote_featured(actor_data: dict, sign_as: User | None = None):
    """Fetch a remote user's featured (pinned) collection.

    Returns a list of pinned post AP IDs, or None if the actor exposes no
    featured collection or it could not be fetched.
    """
    featured_url = ""
    feat = actor_data.get("featured")
    if isinstance(feat, str):
        featured_url = feat
    elif isinstance(feat, dict):
        featured_url = feat.get("id", "")
    if not featured_url:
        feat = actor_data.get("featuredCollection")
        if isinstance(feat, str):
            featured_url = feat
        elif isinstance(feat, dict):
            featured_url = feat.get("id", "")
    if not featured_url:
        return None
    try:
        headers = {"Accept": "application/activity+json, application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\"", "User-Agent": WRIT_USER_AGENT}
        if sign_as:
            parsed = urlparse(featured_url)
            date = datetime.datetime.now(datetime.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            headers["Signature"] = f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            headers["Date"] = date
            headers["Host"] = parsed.netloc
        resp = validated_get(featured_url, headers=headers, timeout=10)
        if resp is None or resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None
    items = data.get("orderedItems") or data.get("items") or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return None
    pinned = []
    for item in items:
        if isinstance(item, str):
            if item:
                pinned.append(item)
        elif isinstance(item, dict):
            itype = item.get("type", "")
            if itype in ("OrderedCollection", "Collection"):
                continue
            pid = item.get("id", "")
            if pid:
                pinned.append(pid)
    return pinned


def _resolve_actor(actor_url: str, force_refresh: bool = False, sign_as: User | None = None, lightweight: bool = False, timeout: int = 10) -> User | None:
    """Resolve a remote actor, creating/updating the local User row.

    원격 pinned 동기화는 하지 않는다(순환 참조 방지). lightweight=False로
    결의된 경우 반환되는 User에 ``pending_pinned_ap_ids`` 속성을 부여하므로,
    호출자(_fetch_actor._resolve_actor 랩퍼)가 이를 _sync_remote_pinned_posts로
    처리한다.
    """
    _actor_domain = urlparse(actor_url).hostname or ""
    _own_domain = urlparse(BASE_URL).hostname or ""
    if _actor_domain and _actor_domain == _own_domain:
        _u = parse_username_from_url(actor_url)
        if _u:
            with get_session() as _s:
                local = _s.query(User).filter(User.username == _u, User.is_remote == False).first()
                if local:
                    return local
    with get_session() as session:
        user = session.query(User).filter_by(remote_url=actor_url).first()
        if user and not force_refresh:
            return user
        # Fallback: normalize /@username -> /users/username
        if not user:
            p = urlparse(actor_url)
            if "/@" in p.path:
                alt_url = f"{p.scheme}://{p.netloc}/users/{p.path.split('/@')[-1]}"
                user = session.query(User).filter_by(remote_url=alt_url).first()
                if user and not force_refresh:
                    return user

    # Convert web URL /@username to AP URL /users/username before fetching
    _p = urlparse(actor_url)
    if "/@" in _p.path:
        _uname = _p.path.split("/@")[-1].strip("/")
        if _uname and "/" not in _uname:
            actor_url = f"{_p.scheme}://{_p.netloc}/users/{_uname}"
            _webfinger_user = _uname
            _webfinger_domain = _p.netloc
        else:
            _webfinger_user = None
            _webfinger_domain = None
    else:
        _webfinger_user = None
        _webfinger_domain = None

    data = None
    if sign_as:
        try:
            date = datetime.datetime.now(datetime.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
            parsed = urlparse(actor_url)
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            sig_header = f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            headers = {"Accept": "application/activity+json", "Signature": sig_header, "Date": date, "Host": parsed.netloc}
            data = _fetch_ap_json(actor_url, headers=headers, timeout=timeout)
        except Exception:
            pass

    if data is None:
        data = _fetch_ap_json(actor_url, timeout=timeout)

    # Webfinger fallback for /@username URLs that /users/username doesn't serve
    if data is None and _webfinger_user and _webfinger_domain:
        try:
            wf_url = f"https://{_webfinger_domain}/.well-known/webfinger?resource=acct:{_webfinger_user}@{_webfinger_domain}"
            wf_resp = safe_fetch(wf_url, timeout=timeout, headers={"Accept": "application/jrd+json, application/json"})
            if wf_resp and wf_resp.status_code == 200:
                wf_data = wf_resp.json()
                for link in wf_data.get("links", []):
                    if link.get("type") in ("application/activity+json", "application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\""):
                        alt_actor = link.get("href", "")
                        if alt_actor:
                            data = _fetch_ap_json(alt_actor, timeout=timeout)
                            if data:
                                actor_url = alt_actor
                                break
        except Exception:
            pass

    if not data:
        return None


    # Verify the response's id domain matches the requested URL's domain
    resp_id = data.get("id", "")
    canonical_url = resp_id or actor_url
    if resp_id:
        req_domain = urlparse(actor_url).hostname or ""
        resp_domain = urlparse(resp_id).hostname or ""
        if req_domain and resp_domain and req_domain != resp_domain:
            logger.warning("Domain mismatch: requested %s, response claims %s", req_domain, resp_domain)
            return None

    preferred_username = data.get("preferredUsername", "")
    if not preferred_username:
        return None
    # 일부 서버는 preferredUsername에 도메인을 포함해 보냄 (e.g. "user@domain")
    if "@" in preferred_username:
        preferred_username = preferred_username.split("@")[0]

    parsed = urlparse(actor_url)
    domain = parsed.netloc
    local_username = f"{preferred_username}@{domain}"

    # Extract avatar and header URL
    avatar_url = ""
    icon = data.get("icon", {})
    if isinstance(icon, dict):
        avatar_url = icon.get("url", "")
    elif isinstance(icon, list):
        avatar_url = icon[0].get("url", "") if icon else ""

    header_url = ""
    image_field = data.get("image", {})
    if isinstance(image_field, dict):
        header_url = image_field.get("url", "")
    elif isinstance(image_field, list):
        header_url = image_field[0].get("url", "") if image_field else ""

    public_key_pem = ""
    if "publicKey" in data:
        public_key_pem = data["publicKey"].get("publicKeyPem", "")

    # Download images BEFORE opening DB session to avoid holding connections during network I/O
    _dl_avatar = ""
    _dl_header = ""
    _dl_followers = None
    _dl_following = None
    _pinned_ap_ids = None
    if not lightweight:
        base_username_clean = local_username.replace("@", "_")
        _dl_avatar = _save_remote_avatar(avatar_url, base_username_clean) if avatar_url else ""
        _dl_header = _save_remote_image(header_url, "headers", base_username_clean) if header_url else ""
        _dl_followers = _fetch_remote_count(data.get("followers", ""), sign_as)
        _dl_following = _fetch_remote_count(data.get("following", ""), sign_as)
        _pinned_ap_ids = _fetch_remote_featured(data, sign_as)

    result_user = None
    with get_session() as session:
        existing = session.query(User).filter_by(remote_url=actor_url).first()

        if existing:
            existing.public_key = public_key_pem
            existing.display_name = data.get("name", existing.display_name)
            existing.summary = data.get("summary", existing.summary)
            existing.remote_url = canonical_url
            existing.inbox_url = data.get("inbox", existing.inbox_url)
            existing.shared_inbox_url = data.get("endpoints", {}).get("sharedInbox", existing.shared_inbox_url)
            existing.is_locked = data.get("manuallyApprovesFollowers", existing.is_locked)
            existing.profile_url = data.get("url", existing.profile_url or "")
            if _dl_avatar:
                existing.profile_image = _dl_avatar
            if _dl_header:
                existing.header_image = _dl_header
            existing.custom_fields = _extract_custom_fields(data.get("attachment", []))
            existing.remote_followers_count = _dl_followers
            existing.remote_following_count = _dl_following
            session.commit()
            if not lightweight:
                # Process emoji tags AFTER session closes to avoid holding connection during HTTP
                with get_session() as emoji_s:
                    _process_emoji_tags(data.get("tag", []), emoji_s)
                    emoji_s.commit()
            result_user = existing

        # Also check by username in case remote_url is missing/stale
        if result_user is None:
            by_username = session.query(User).filter_by(username=local_username).first()
            if by_username:
                by_username.remote_url = canonical_url
                by_username.public_key = public_key_pem or by_username.public_key
                by_username.display_name = data.get("name", by_username.display_name)
                by_username.summary = data.get("summary", by_username.summary)
                by_username.profile_url = data.get("url", by_username.profile_url or "")
                if _dl_avatar:
                    by_username.profile_image = _dl_avatar
                if _dl_header:
                    by_username.header_image = _dl_header
                by_username.custom_fields = _extract_custom_fields(data.get("attachment", []))
                by_username.remote_followers_count = _dl_followers
                by_username.remote_following_count = _dl_following
                session.commit()
                if not lightweight:
                    with get_session() as emoji_s:
                        _process_emoji_tags(data.get("tag", []), emoji_s)
                        emoji_s.commit()
                result_user = by_username

        if result_user is None:
            # Ensure uniqueness
            base_username = local_username
            counter = 1
            while session.query(User).filter_by(username=local_username).first():
                local_username = f"{base_username}_{counter}"
                counter += 1

            priv, pub = generate_keypair()
            user = User(
                username=local_username,
                display_name=data.get("name", preferred_username),
                summary=data.get("summary", ""),
                email=f"remote-{uuid.uuid4().hex}@remote.placeholder.invalid",
                password_hash="remote_user",
                private_key=encrypt_key(priv, SECRET_KEY),
                public_key=public_key_pem or pub,
                is_remote=True,
                remote_url=canonical_url,
                profile_url=data.get("url", ""),
                inbox_url=data.get("inbox", ""),
                shared_inbox_url=data.get("endpoints", {}).get("sharedInbox", ""),
                profile_image=_dl_avatar,
                header_image=_dl_header,
                is_locked=data.get("manuallyApprovesFollowers", False),
                custom_fields=_extract_custom_fields(data.get("attachment", [])),
                remote_followers_count=_dl_followers,
                remote_following_count=_dl_following,
            )
            session.add(user)
            session.flush()
            session.commit()
            if not lightweight:
                with get_session() as emoji_s:
                    _process_emoji_tags(data.get("tag", []), emoji_s)
                    emoji_s.commit()
            result_user = user

    if _pinned_ap_ids is not None:
        # 호출자(_fetch_actor 랩퍼)가 _sync_remote_pinned_posts로 처리한다.
        result_user.pending_pinned_ap_ids = _pinned_ap_ids
    return result_user
