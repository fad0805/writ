import io
import os
import re
import time
import datetime
import json
import logging
import threading
import uuid
import html
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config.settings import BASE_URL, SECRET_KEY
from app.db.database import get_session
from app.models import User, Post, Tag, CustomEmoji
from app.utils.to_ap_serializer import to_ap_actor
from app.utils.crypto import generate_keypair, sign_string, encrypt_key, get_private_key
from app.utils.content_parser import _sanitize_html, process_post_content
from app.core.activitypub._utils import (
    _validate_url, _safe_fetch, _validated_get, _federation_allowed,
    _get_instance_actor, _parse_username_from_url, _extract_remote_url,
    WRIT_USER_AGENT,
)
from app.core.activitypub._media import _save_remote_image, _save_remote_avatar, _cache_remote_media
from app.core.activitypub._emoji import _process_emoji_tags

logger = logging.getLogger("writ.activitypub")


def _fetch_ap_json(url, headers=None, timeout=10, _depth=0):
    """Fetch AP JSON. If server returns HTML, parse for rel=alternate AP link and retry."""
    if _depth > 2:
        return None
    unsigned_headers = {"Accept": "application/activity+json"}
    try:
        resp = _safe_fetch(url, timeout=timeout, headers=headers or unsigned_headers)
        if not resp or resp.status_code != 200:
            return None
        ct = resp.headers.get("content-type", "")
        body = resp.text[:200000] if "json" not in ct and "activity" not in ct else ""
        if body:
            alt_m = re.search(r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/activity\+json["\'][^>]+href=["\']([^"\']+)["\']', body, re.I)
            if not alt_m:
                alt_m = re.search(r'<link[^>]+type=["\']application/activity\+json["\'][^>]+rel=["\']alternate["\'][^>]+href=["\']([^"\']+)["\']', body, re.I)
            if not alt_m:
                alt_m = re.search(r'href=["\']([^"\']+)["\'][^>]*type=["\']application/activity\+json["\']', body, re.I)
            if alt_m:
                return _fetch_ap_json(alt_m.group(1), headers=unsigned_headers, timeout=timeout, _depth=_depth + 1)
            return None
        return resp.json()
    except Exception:
        return None


def _parse_username_from_url(url: str) -> str:
    url = url.rstrip("/")
    # Handle /users/{username} or /@{username}
    match = re.search(r'/(?:users/)?@?([\w.\-]+)$', url)
    if match:
        return match.group(1)
    # Fallback: last segment
    return url.split("/")[-1]


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


def _fetch_remote_count(collection_url: str, sign_as: Optional[User] = None) -> int:
    """Fetch totalItems from a remote ActivityPub collection (followers/following)."""
    if not collection_url:
        return 0
    try:
        headers = {"Accept": "application/activity+json, application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\"", "User-Agent": WRIT_USER_AGENT}
        if sign_as:
            parsed = urlparse(collection_url)
            date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            headers["Signature"] = f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            headers["Date"] = date
            headers["Host"] = parsed.netloc
        resp = _validated_get(collection_url, headers=headers, timeout=10)
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            return int(data.get("totalItems", 0))
    except Exception:
        pass
    return 0


def _fetch_remote_featured(actor_data: dict, sign_as: Optional[User] = None):
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
            date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            headers["Signature"] = f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            headers["Date"] = date
            headers["Host"] = parsed.netloc
        resp = _validated_get(featured_url, headers=headers, timeout=10)
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


def _sync_remote_pinned_posts(user_id: int, pinned_ap_ids: list, sign_as: Optional[User] = None):
    """Resolve remote featured (pinned) AP IDs to local Post IDs and store on the user.

    Empty pinned_ap_ids clears existing pins (the remote user unpinned everything).
    """
    with get_session() as session:
        user = session.query(User).get(user_id)
        if not user or not user.is_remote:
            return
        signer = sign_as or _get_instance_actor(session)
        new_pinned = []
        for ap_id in pinned_ap_ids:
            post = session.query(Post).filter_by(ap_id=ap_id).first()
            if post and not post.is_deleted:
                new_pinned.append(post.id)
                continue
            if signer:
                try:
                    fetched = _fetch_remote_post(ap_id, signer, session)
                    if fetched:
                        new_pinned.append(fetched.id)
                except Exception as e:
                    logger.warning("[PINNED] failed to fetch %s: %s", ap_id, e)
        user.pinned_posts = new_pinned
        session.commit()


def _resolve_actor(actor_url: str, force_refresh: bool = False, sign_as: Optional[User] = None) -> Optional[User]:
    _actor_domain = urlparse(actor_url).hostname or ""
    _own_domain = urlparse(BASE_URL).hostname or ""
    if _actor_domain and _actor_domain == _own_domain:
        _u = _parse_username_from_url(actor_url)
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
            date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
            parsed = urlparse(actor_url)
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            sig_header = f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            headers = {"Accept": "application/activity+json", "Signature": sig_header, "Date": date, "Host": parsed.netloc}
            data = _fetch_ap_json(actor_url, headers=headers)
        except Exception:
            pass

    if data is None:
        data = _fetch_ap_json(actor_url)

    # Webfinger fallback for /@username URLs that /users/username doesn't serve
    if data is None and _webfinger_user and _webfinger_domain:
        try:
            wf_url = f"https://{_webfinger_domain}/.well-known/webfinger?resource=acct:{_webfinger_user}@{_webfinger_domain}"
            wf_resp = _safe_fetch(wf_url, timeout=10, headers={"Accept": "application/jrd+json, application/json"})
            if wf_resp and wf_resp.status_code == 200:
                wf_data = wf_resp.json()
                for link in wf_data.get("links", []):
                    if link.get("type") in ("application/activity+json", "application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\""):
                        alt_actor = link.get("href", "")
                        if alt_actor:
                            data = _fetch_ap_json(alt_actor)
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
    base_username_clean = local_username.replace("@", "_")
    _dl_avatar = _save_remote_avatar(avatar_url, base_username_clean) if avatar_url else ""
    _dl_header = _save_remote_image(header_url, "headers", base_username_clean) if header_url else ""
    _dl_followers = _fetch_remote_count(data.get("followers", ""), sign_as)
    _dl_following = _fetch_remote_count(data.get("following", ""), sign_as)
    _pinned_ap_ids = _fetch_remote_featured(data, sign_as)

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
            session.commit()
            if _pinned_ap_ids is not None:
                _sync_remote_pinned_posts(existing.id, _pinned_ap_ids, sign_as)
            # Process emoji tags AFTER session closes to avoid holding connection during HTTP
            with get_session() as emoji_s:
                _process_emoji_tags(data.get("tag", []), emoji_s)
                emoji_s.commit()
            return existing

        # Also check by username in case remote_url is missing/stale
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
            session.commit()
            if _pinned_ap_ids is not None:
                _sync_remote_pinned_posts(by_username.id, _pinned_ap_ids, sign_as)
            with get_session() as emoji_s:
                _process_emoji_tags(data.get("tag", []), emoji_s)
                emoji_s.commit()
            return by_username

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
        with get_session() as emoji_s:
            _process_emoji_tags(data.get("tag", []), emoji_s)
            emoji_s.commit()
        session.commit()
        if _pinned_ap_ids is not None:
            _sync_remote_pinned_posts(user.id, _pinned_ap_ids, sign_as)
        return user


def _retry_fetch_reply(post_id: int, in_reply_to_ap_id: str, attempt: int = 0):
    """Background: fetch remote parent and link to local post. Max 5 attempts with increasing delay."""
    MAX_ATTEMPTS = 5
    def _worker():
        try:
            with get_session() as s:
                post = s.query(Post).get(post_id)
                if not post or post.in_reply_to_id:
                    return
                existing_parent = s.query(Post).filter_by(ap_id=in_reply_to_ap_id).first()
                if existing_parent:
                    post.in_reply_to_id = existing_parent.id
                    s.commit()
                    return
                signer = s.query(User).filter_by(id=post.author_id).first() or _get_instance_actor(s)
                parent = _fetch_remote_post(in_reply_to_ap_id, signer, s)
                if parent:
                    post.in_reply_to_id = parent.id
                    s.commit()
                elif attempt + 1 < MAX_ATTEMPTS:
                    delay = min(30 * (2 ** attempt), 600)
                    time.sleep(delay)
                    _retry_fetch_reply(post_id, in_reply_to_ap_id, attempt + 1)
                else:
                    logger.warning("[RETRY-REPLY] gave up post_id=%s ap_id=%s after %d attempts", post_id, in_reply_to_ap_id, MAX_ATTEMPTS)
        except Exception as e:
            logger.error("[RETRY-REPLY] failed post_id=%s err=%s", post_id, e, exc_info=True)
    threading.Thread(target=_worker, daemon=True).start()


def _fetch_remote_post(url: str, signer: User, session, _depth=0):
    """Fetch a remote AP object and save it as a Post. Returns the Post or None."""
    if _depth > 3 or not url:
        return None

    print(f"[FETCH-POST] url={url} signer={signer.actor_uri() if signer else 'None'} depth={_depth}", flush=True)

    # Convert web URL /@username/id to AP URL /users/username/statuses/id (Mastodon)
    m = re.match(r'^(https?://[^/]+)/@(\w+(?:@\S+)?)/([a-f0-9]+)(\?.*)?$', url)
    if m:
        base, username, status_id, query = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        url = f"{base}/users/{username}/statuses/{status_id}{query}"
        print(f"[FETCH-POST] Mastodon URL converted to: {url}", flush=True)

    if url.endswith("/activity"):
        url = url[:-len("/activity")]
        print(f"[FETCH-POST] stripped /activity suffix → {url}", flush=True)

    parsed = urlparse(url)
    headers = {"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}

    if not signer:
        try:
            signer = _get_instance_actor(session)
        except Exception:
            pass
    if signer:
        try:
            date_str = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
            path_with_query = parsed.path or "/"
            if parsed.query:
                path_with_query += f"?{parsed.query}"
            signed_string = (
                f"(request-target): get {path_with_query}\n"
                f"host: {parsed.netloc}\n"
                f"date: {date_str}"
            )
            sig = sign_string(signed_string, get_private_key(signer, SECRET_KEY))
            sig_header = (
                f'keyId="{signer.actor_uri()}#main-key",'
                f'headers="(request-target) host date",'
                f'signature="{sig}"'
            )
            headers["Signature"] = sig_header
            headers["Date"] = date_str
            headers["Host"] = parsed.netloc
        except Exception:
            pass

    headers["Accept"] = "application/activity+json"
    data = None
    try:
        resp = _validated_get(url, headers=headers, timeout=10)
        print(f"[FETCH-POST] first attempt url={url} status={resp.status_code if resp else 'None'}", flush=True)
        if resp is not None and resp.status_code == 200:
            data = resp.json()
    except Exception as e:
        logger.error("[FETCH-POST] url=%s error=%s", url, e, exc_info=True)

    if data is None:
        try:
            resp = _validated_get(url, headers=headers, timeout=10)
            print(f"[FETCH-POST] retry url={url} status={resp.status_code if resp else 'None'}", flush=True)
            if resp is not None and resp.status_code == 200:
                data = resp.json()
        except Exception as e:
            logger.error("[FETCH-POST] retry url=%s error=%s", url, e, exc_info=True)

    if data is None:
        print(f"[FETCH-POST] FAILED url={url}", flush=True)
        return None

    obj = data.get("object", data) if isinstance(data, dict) else {}
    if not isinstance(obj, dict):
        print(f"[FETCH-POST] obj not dict url={url}", flush=True)
        return None
    obj_type = obj.get("type", "")
    if obj_type not in ("Note", "Question"):
        print(f"[FETCH-POST] not Note/Question type={obj_type} url={url}", flush=True)
        return None

    ap_id = obj.get("id", url)
    remote_url = _extract_remote_url(obj, ap_id)
    existing = session.query(Post).filter_by(ap_id=ap_id).first()
    if existing and not existing.is_deleted:
        print(f"[FETCH-POST] existing post id={existing.id} ap_id={ap_id}", flush=True)
        return existing

    attributed_to = obj.get("attributedTo", "")
    if isinstance(attributed_to, list):
        attributed_to = attributed_to[0] if attributed_to else ""
    if isinstance(attributed_to, dict):
        attributed_to = attributed_to.get("id", "")
    if not attributed_to:
        print(f"[FETCH-POST] no attributedTo url={url}", flush=True)
        return None

    _resolve_actor(attributed_to, sign_as=signer)
    author = session.query(User).filter_by(remote_url=attributed_to).first()
    if not author:
        print(f"[FETCH-POST] author not found attributed_to={attributed_to}", flush=True)
        return None

    raw_content = obj.get("content", "") or ""
    if not raw_content:
        cm = obj.get("contentMap")
        if isinstance(cm, dict) and cm:
            raw_content = next(iter(cm.values()), "")
    if len(raw_content) > 65536:
        raw_content = raw_content[:65536]
    content = process_post_content(_sanitize_html(raw_content), obj)
    summary = obj.get("summary", "")

    to = obj.get("to", [])
    if isinstance(to, str): to = [to]
    cc = obj.get("cc", [])
    if isinstance(cc, str): cc = [cc]
    all_auds = to + cc
    pub = "https://www.w3.org/ns/activitystreams#Public"
    pub_set = {pub, "as:Public"}

    tags = obj.get("tag", [])
    if isinstance(tags, dict): 
        tags = [tags]
    elif not isinstance(tags, list): 
        tags = []

    has_mention_tag = False
    mentioned_ids = []
    hashtag_list = []
    for t in tags:
        if not isinstance(t, dict):
            continue
        is_mention_type = t.get("type") == "Mention"
        name_val = t.get("name", "") or ""
        is_double_at = name_val.startswith("@") and name_val.count("@") >= 2
        if is_mention_type or is_double_at:
            has_mention_tag = True
            actor_href = t.get("href", "")
            if not actor_href:
                continue
            try:
                _resolve_actor(actor_href)
                mentioned_user = session.query(User).filter_by(remote_url=actor_href).first()
                if mentioned_user:
                    mentioned_ids.append(mentioned_user.id)
            except Exception as e:
                logger.error("[FETCH-POST] Failed to resolve mentioned actor=%s: %s", actor_href, e, exc_info=True)
        elif t.get('type') == "Hashtag":
            tag_name = (t.get("name", "") or "").lstrip("#").strip().lower()
            if tag_name:
                existing_tag = session.query(Tag).filter_by(name=tag_name).first()
                if existing_tag:
                    hashtag_list.append(existing_tag)
                else:
                    hashtag_list.append(Tag(name=tag_name))
    mentioned_ids = list(set(mentioned_ids))

    if pub_set & set(to):
        vis = "public"
    elif pub_set & set(cc):
        vis = "home"
    elif any(a.endswith("/followers") for a in all_auds):
        vis = "followers"
    elif not (pub_set & set(all_auds)) and has_mention_tag:
        vis = "mention"
    elif all(a.startswith("http") for a in all_auds if a):
        vis = "mention"
    else:
        vis = "home"

    instance_actor = session.query(User).filter_by(username='actor').first()
    in_reply_to_ap = obj.get("inReplyTo", "")
    if isinstance(in_reply_to_ap, dict):
        in_reply_to_ap = in_reply_to_ap.get("id", "")

    in_reply_to_id = None
    if in_reply_to_ap:
        parent = session.query(Post).filter_by(ap_id=in_reply_to_ap).first()
        if parent:
            in_reply_to_id = parent.id
        else:
            parent = _fetch_remote_post(in_reply_to_ap, instance_actor, session, _depth + 1)
            if parent:
                in_reply_to_id = parent.id

    # 💡 [해결] 원격 오브젝트에서 인용 URL(quoteUrl) 추출 및 연동 처리
    quote_url = obj.get("quoteUrl", "")
    quote_id = None
    if quote_url:
        quoted_post = session.query(Post).filter_by(ap_id=quote_url).first()
        if not quoted_post:
            # 내 DB에 없다면 인용된 원본 게시물도 연합망에서 깊이(depth)를 더해 긁어옵니다.
            quoted_post = _fetch_remote_post(quote_url, signer, session, _depth + 1)
        if quoted_post:
            quote_id = quoted_post.id

    _process_emoji_tags(obj.get("tag", []), session)
    session.flush()

    raw_attachments = obj.get("attachment", [])
    if isinstance(raw_attachments, dict):
        raw_attachments = [raw_attachments]
    elif not isinstance(raw_attachments, list):
        raw_attachments = []
    media_list = []
    _att_has_sensitive = False
    for att in raw_attachments:
        if not isinstance(att, dict):
            continue
        att_type = att.get("mediaType", "")
        att_as2_type = att.get("type", "")
        att_url = ""
        if isinstance(att.get("url"), str):
            att_url = att["url"]
        elif isinstance(att.get("url"), dict):
            att_url = att["url"].get("href", "")
        if not att_url:
            continue
        if att.get("sensitive", False):
            _att_has_sensitive = True
        cached = _cache_remote_media(att_url)
        if att_type.startswith("image/") or att_as2_type == "Image":
            media_list.append({"url": cached, "type": "image"})
        elif att_type.startswith("video/") or att_as2_type == "Video":
            media_list.append({"url": cached, "type": "video"})
        elif att_as2_type == "Document" or att_type.startswith("audio/"):
            if att_type.startswith("image/"):
                mtype = "image"
            elif att_type.startswith("video/"):
                mtype = "video"
            else:
                mtype = "image"  # fallback for missing mediaType
            media_list.append({"url": cached, "type": mtype})

    # 💡 Post 모델 생성 시 quote_id (또는 모델 설계에 맞춘 인용 필드명) 채워넣기
    post = Post(
        author_id=author.id,
        content=content,
        summary=summary,
        visibility=vis,
        ap_id=ap_id,
        remote_url=remote_url,
        in_reply_to_ap_id=in_reply_to_ap,
        in_reply_to_id=in_reply_to_id,
        quote_of_id=quote_id,
        quote_of_ap_id=quote_url,
        mentioned_user_ids=mentioned_ids,
        media_attachments=media_list if media_list else None,
        is_sensitive=obj.get("sensitive", False) or _att_has_sensitive,
        tag_list=hashtag_list,
    )
    published = obj.get("published", "")
    if published:
        try:
            post.created_at = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))
        except Exception:
            pass
    session.add(post)
    try:
        session.flush()
    except Exception:
        session.rollback()
        return session.query(Post).filter_by(ap_id=ap_id).first()

    # 💡 만약 인용 글이 제대로 매칭되었다면 하단의 링크 미리보기(외부링크 상자) 연산을 건너뜁니다.
    if post.quote_of_id:
        return post

    # 원격 포스트에 포함된 URL의 링크 미리보기 fetch
    _url_match = re.search(r'https?://(?:(?!/tags/)[^\s<>"\')\]#])+', content or "")
    if _url_match:
        _url = _url_match.group(0)
        try:
            _resp = httpx.get(_url, headers={"User-Agent": "WRIT/1.0"}, timeout=5, follow_redirects=True)
            if _resp.status_code == 200:
                _html = _resp.text
                def _og(n):
                    _m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', _html, _re.I)
                    if not _m:
                        _m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', _html, _re.I)
                    return _m.group(1) if _m else ""
                _og_title = _og("title") or (re.search(r'<title>([^<]*)</title>', _html, re.I).group(1) if re.search(r'<title>([^<]*)</title>', _html, re.I) else "")
                _og_desc = _og("description")
                _og_img = _og("image")
                if _og_img and _og_img.startswith("/"):
                    _p = urlparse(_url)
                    _og_img = f"{_p.scheme}://{_p.netloc}{_og_img}"
                if _og_title:
                    post.link_preview = {"url": _url, "title": html.unescape(_og_title[:200]), "description": html.unescape(_og_desc[:400]) if _og_desc else "", "image": _og_img or ""}
        except Exception:
            pass

    return post
