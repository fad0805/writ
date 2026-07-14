import datetime
import io
import ipaddress
import json
import hashlib
import logging
import os
import re
import socket
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.models import User, Post, Follow, Like, Boost, Vote, Notification, Report, RemoteMedia, CustomEmoji, FederationBlock, AllowedServer, MutedServer, ServerSetting, UserBlock, get_session
from app.config import BASE_URL, SECRET_KEY
from app.crypto_utils import generate_keypair, sign_string, encrypt_key, get_private_key


logger = logging.getLogger("writ.activitypub")


def _federation_allowed(domain: str) -> bool:
    if not domain:
        return False
    from app.config import DOMAIN
    if domain.lower().strip() == DOMAIN.lower().strip():
        return True
    with get_session() as s:
        try:
            settings = s.query(ServerSetting).first()
            if not settings:
                return True
            mode = settings.federation_mode or "blacklist"
            domain = domain.lower().strip()
            if mode == "whitelist":
                allowed = s.query(AllowedServer).filter_by(domain=domain).first()
                return allowed is not None
            else:
                blocked = s.query(FederationBlock).filter_by(domain=domain).first()
                return blocked is None
        except Exception:
            return True


_SAFE_TAGS = {"p", "br", "a", "strong", "em", "b", "i", "u", "s", "ul", "ol", "li", "blockquote", "code", "pre", "span", "img"}
_SAFE_SCHEMES = {"http", "https", "mailto"}
_SAFE_ATTRS = {"a": {"href", "rel", "class"}, "span": {"class"}, "code": {"class"}, "pre": {"class"}, "img": {"src", "alt", "class", "title"}}


def _sanitize_html(html: str) -> str:
    """Strip dangerous HTML tags/attributes, keep only safe ones."""
    # Remove script/style blocks and their content
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove remaining script/style self-closing tags
    html = re.sub(r'<(script|style)[^>]*/?>', '', html, flags=re.IGNORECASE)

    def _tag_filter(m):
        tag = m.group(0)
        # Parse tag name
        name_match = re.match(r'</?(\w+)', tag)
        if not name_match:
            return ''
        name = name_match.group(1).lower()
        if name not in _SAFE_TAGS:
            return ''
        # For closing tags, return as-is
        if tag.startswith('</'):
            return tag
        # For opening tags, filter attributes
        allowed = _SAFE_ATTRS.get(name, set())
        attrs = re.findall(r'''([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')''', tag)
        safe_attrs = []
        for attr_name, v1, v2 in attrs:
            val = v1 or v2 or ''
            attr_lower = attr_name.lower()
            if attr_lower.startswith('on'):
                continue
            if attr_lower == 'href' and name == 'a':
                scheme = val.split(':', 1)[0].lower() if ':' in val else ''
                if scheme not in _SAFE_SCHEMES:
                    continue
            if attr_lower in allowed:
                safe_attrs.append(f'{attr_name}="{val}"')
        if not safe_attrs:
            return f'<{name}>'
        return f'<{name} {" ".join(safe_attrs)}>'

    html = re.sub(r'<[^>]+>', _tag_filter, html)
    return html


def _normalize_mentions(html: str) -> str:
    """Convert Mastodon-style mention HTML to plain @username text."""
    def _strip_mention(m):
        text = re.sub(r'<[^>]+>', '', m.group(0))
        match = re.search(r'@(\w+)', text)
        return '@' + match.group(1) if match else text
    # <span class="h-card"> wrapping (optional) + <a with u-url mention class
    html = re.sub(
        r'<span[^>]*class="[^"]*\bh-card\b[^"]*"[^>]*>\s*<a[^>]*class="[^"]*\bu-url mention\b[^"]*"[^>]*>.*?</a>\s*</span>',
        _strip_mention, html, flags=re.IGNORECASE | re.DOTALL
    )
    # <a with u-url mention class (without wrapper)
    html = re.sub(
        r'<a[^>]*class="[^"]*\bu-url mention\b[^"]*"[^>]*>.*?</a>',
        _strip_mention, html, flags=re.IGNORECASE | re.DOTALL
    )
    return html


_PRIVATE_SUBNETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]


def _validate_url(url: str) -> bool:
    """Reject URLs pointing to private/internal IPs (SSRF protection)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # Allow configured allowed domains and own server
    from app.config import DOMAIN, BASE_URL
    _SSRF_ALLOWED = {s.strip() for s in os.environ.get("SSRF_ALLOWED_DOMAINS", "").split(",") if s.strip()}
    own_domain = urlparse(BASE_URL).hostname or DOMAIN
    _SSRF_ALLOWED.add(own_domain)
    if host in _SSRF_ALLOWED:
        return True
    # Block obviously private hostnames without DNS resolution
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    if host.endswith(".localhost"):
        return False
    # Try to resolve and check against private subnets (IPv4 + IPv6)
    try:
        addrs = socket.getaddrinfo(host, 80, family=socket.AF_UNSPEC)
        for addr in addrs:
            ip = ipaddress.ip_address(addr[4][0])
            for net in _PRIVATE_SUBNETS:
                if ip in net:
                    return False
    except (socket.gaierror, OSError, ValueError):
        pass
    # Also check if the raw string is an IP literal
    try:
        ip = ipaddress.ip_address(host)
        for net in _PRIVATE_SUBNETS:
            if ip in net:
                return False
    except ValueError:
        pass
    return True


def _parse_username_from_url(url: str) -> str:
    url = url.rstrip("/")
    # Handle /users/{username} or /@{username}
    match = re.search(r'/(?:users/)?@?([\w.\-]+)$', url)
    if match:
        return match.group(1)
    # Fallback: last segment
    return url.split("/")[-1]


def get_actor(username: str):
    with get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return None
        return user.to_ap_actor()


def get_outbox(username: str, page: Optional[int] = None):
    with get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return None

        query = session.query(Post).filter(
            Post.author_id == user.id,
            Post.is_deleted == False,
            Post.novel_id.is_(None),
            Post.visibility.in_(["public", "unlisted", "home"]),
        ).order_by(Post.created_at.desc())

        total = query.count()
        outbox_url = user.outbox_uri()
        if page is not None:
            offset = (page - 1) * 20
            posts = query.offset(offset).limit(20).all()
            items = [p.to_ap_create() for p in posts]
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{outbox_url}?page={page}",
                "type": "OrderedCollectionPage",
                "totalItems": total,
                "partOf": outbox_url,
                "orderedItems": items,
                "next": f"{outbox_url}?page={page + 1}" if offset + 20 < total else None,
                "prev": f"{outbox_url}?page={page - 1}" if page > 1 else None,
            }
        else:
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": outbox_url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{outbox_url}?page=1",
            }


def get_followers(username: str, page: Optional[int] = None):
    with get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return None

        if user.follow_list_visibility == "private":
            return {"@context": "https://www.w3.org/ns/activitystreams", "id": user.followers_uri(), "type": "OrderedCollection", "totalItems": 0, "first": f"{user.followers_uri()}?page=1"}

        query = session.query(Follow).filter(
            Follow.following_id == user.id,
            Follow.accepted == True,
        )

        total = query.count()
        url = user.followers_uri()

        if page is not None:
            offset = (page - 1) * 20
            follows = query.offset(offset).limit(20).all()
            items = [f.follower.actor_uri() for f in follows]
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{url}?page={page}",
                "type": "OrderedCollectionPage",
                "totalItems": total,
                "partOf": url,
                "orderedItems": items,
            }
        else:
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{url}?page=1",
            }


def get_following(username: str, page: Optional[int] = None):
    with get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return None

        if user.follow_list_visibility == "private":
            return {"@context": "https://www.w3.org/ns/activitystreams", "id": user.following_uri(), "type": "OrderedCollection", "totalItems": 0, "first": f"{user.following_uri()}?page=1"}

        query = session.query(Follow).filter(
            Follow.follower_id == user.id,
            Follow.accepted == True,
        )

        total = query.count()
        url = user.following_uri()

        if page is not None:
            offset = (page - 1) * 20
            follows = query.offset(offset).limit(20).all()
            items = [f.following.actor_uri() for f in follows]
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{url}?page={page}",
                "type": "OrderedCollectionPage",
                "totalItems": total,
                "partOf": url,
                "orderedItems": items,
            }
        else:
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{url}?page=1",
            }


def handle_inbox(activity: dict) -> tuple[int, str]:
    atype = activity.get("type")
    actor = activity.get("actor")

    if isinstance(actor, list):
        actor = actor[0]

    actor_domain = urlparse(actor).hostname or "" if actor and isinstance(actor, str) else ""
    print(f"[INBOX] atype={atype} actor_domain={actor_domain}", flush=True)

    # Check federation rules for the actor's domain
    if actor and isinstance(actor, str):
        actor_domain = urlparse(actor).hostname or ""
        if not _federation_allowed(actor_domain):
            logger.info("Rejected inbox activity from blocked domain: %s", actor_domain)
            return (403, "Domain not allowed")

    if atype == "Follow":
        return _handle_follow(activity)
    elif atype == "Accept":
        return _handle_accept(activity)
    elif atype == "Reject":
        return _handle_reject(activity)
    elif atype == "Create":
        return _handle_create(activity)
    elif atype == "Like":
        return _handle_like(activity)
    elif atype == "Announce":
        return _handle_announce(activity)
    elif atype == "Undo":
        return _handle_undo(activity)
    elif atype == "Update":
        return _handle_update(activity)
    elif atype == "Delete":
        return _handle_delete(activity)
    elif atype == "Flag":
        return _handle_flag(activity)
    elif atype == "Move":
        return _handle_move(activity)
    elif atype == "Vote":
        return _handle_vote(activity)
    elif atype == "EmojiReact":
        return _handle_like(activity)
    elif atype == "Block":
        return _handle_block(activity)
    else:
        return (202, f"Accepted {atype}")


def _safe_fetch(url, timeout=10, max_size=5*1024*1024, headers=None):
    """HTTP GET with redirect validation and size limit."""
    if not _validate_url(url):
        return None
    domain = urlparse(url).hostname or ""
    if not _federation_allowed(domain):
        logger.info("Federation blocked for domain: %s", domain)
        return None
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    original_send = client.send
    def _validated_send(request, **kwargs):
        if _validate_url(str(request.url)):
            return original_send(request, **kwargs)
        raise httpx.InvalidURL(f"Blocked redirect to {request.url}")
    client.send = _validated_send
    try:
        resp = client.get(url, headers=headers or {})
        if resp.status_code != 200:
            return None
        if len(resp.content) > max_size:
            return None
        return resp
    except Exception as e:
        return None
    finally:
        client.close()

_REMOTE_MEDIA_MAX_SIZE = 10 * 1024 * 1024
_REMOTE_MEDIA_EXPIRY_DAYS = 30


def _cache_remote_media(remote_url: str) -> str:
    from app.models import RemoteMedia
    from app.utils.storage import get_storage
    if not _validate_url(remote_url):
        return remote_url
    with get_session() as s:
        existing = s.query(RemoteMedia).filter_by(remote_url=remote_url).first()
        if existing and existing.expires_at and existing.expires_at > datetime.datetime.now(datetime.timezone.utc):
            return existing.local_url
    try:
        resp = _safe_fetch(remote_url, max_size=_REMOTE_MEDIA_MAX_SIZE)
        if not resp:
            return remote_url
        data = resp.content
        ext = remote_url.rsplit(".", 1)[-1].lower() if "." in remote_url else ""
        is_image = ext in ("jpg", "jpeg", "png", "gif", "webp")
        if is_image and len(data) < _REMOTE_MEDIA_MAX_SIZE:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=85)
            data = out.getvalue()
            ext = "webp"
        name = f"remote_{uuid.uuid4().hex[:12]}.{ext}"
        key = f"media/remote/{name}"
        storage = get_storage()
        ct = f"image/{ext}" if is_image else "application/octet-stream"
        local_url = storage.save(key, data, ct)
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=_REMOTE_MEDIA_EXPIRY_DAYS)
        with get_session() as s:
            existing2 = s.query(RemoteMedia).filter_by(remote_url=remote_url).first()
            if existing2:
                return existing2.local_url
            s.add(RemoteMedia(remote_url=remote_url, local_url=local_url, size=len(data), expires_at=expires))
            s.commit()
        return local_url
    except Exception as e:
        logger.warning("Failed to cache remote media %s: %s", remote_url, e)
    return remote_url


def _cleanup_expired_media():
    from app.models import RemoteMedia
    from app.utils.storage import get_storage
    storage = get_storage()
    try:
        with get_session() as s:
            items = s.query(RemoteMedia).filter(RemoteMedia.expires_at < datetime.datetime.now(datetime.timezone.utc)).all()
            for item in items:
                try:
                    storage.delete(item.local_url)
                except Exception:
                    pass
                s.delete(item)
            s.commit()
    except Exception as e:
        logger.warning("Failed to cleanup expired media: %s", e)


_REMOTE_POST_RETENTION_DAYS = 90
_PROCESSED_ACTIVITY_RETENTION_DAYS = 7
_REMOTE_USER_CLEANUP_DAYS = 30


def _cleanup_remote_data():
    """Remove old remote posts, processed activities, and stale remote users."""
    cutoff = datetime.datetime.now(datetime.timezone.utc)
    try:
        with get_session() as s:
            # Clean old remote posts
            post_cutoff = cutoff - datetime.timedelta(days=_REMOTE_POST_RETENTION_DAYS)
            old_remote_posts = s.query(Post).filter(
                Post.author.has(is_remote=True),
                Post.created_at < post_cutoff,
            ).limit(500).all()
            for p in old_remote_posts:
                s.delete(p)
            if old_remote_posts:
                logger.info("Cleaned %d old remote posts", len(old_remote_posts))

            # Clean old processed activities (dedup tracking)
            pa_cutoff = cutoff - datetime.timedelta(days=_PROCESSED_ACTIVITY_RETENTION_DAYS)
            from app.models import ProcessedActivity
            old_pa = s.query(ProcessedActivity).filter(
                ProcessedActivity.created_at < pa_cutoff
            ).limit(1000).all()
            for pa in old_pa:
                s.delete(pa)
            if old_pa:
                logger.info("Cleaned %d old processed activities", len(old_pa))

            # Clean stale remote users with no relationships
            user_cutoff = cutoff - datetime.timedelta(days=_REMOTE_USER_CLEANUP_DAYS)
            stale_remotes = s.query(User).filter(
                User.is_remote == True,
                User.created_at < user_cutoff,
            ).all()
            removed = 0
            for u in stale_remotes:
                follows = s.query(Follow).filter(
                    (Follow.follower_id == u.id) | (Follow.following_id == u.id)
                ).count()
                posts = s.query(Post).filter_by(author_id=u.id).count()
                if follows == 0 and posts == 0:
                    s.delete(u)
                    removed += 1
            if removed:
                logger.info("Cleaned %d stale remote users", removed)
            s.commit()
    except Exception as e:
        logger.warning("Failed to cleanup remote data: %s", e)


def _save_remote_image(image_url: str, prefix: str, local_username: str, old_url: str = "") -> str:
    """Download remote image and save as WebP, return URL. If old_url given, delete it after."""
    from app.utils.storage import get_storage
    if not _validate_url(image_url):
        return ""
    ext = image_url.rsplit(".", 1)[-1].lower() if "." in image_url else "jpg"
    is_gif = ext == "gif"
    try:
        import httpx
        import io
        from PIL import Image as PILImage
        r = httpx.get(image_url, timeout=15, follow_redirects=True)
        if r.status_code == 200 and len(r.content) <= 10 * 1024 * 1024:
            if is_gif:
                filename = f"{uuid.uuid4().hex}.gif"
                key = f"{prefix}/remote/{filename}"
                storage = get_storage()
                new_url = storage.save(key, r.content, "image/gif")
            else:
                img = PILImage.open(io.BytesIO(r.content))
                if img.mode in ("RGBA", "P"):
                    bg = PILImage.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                    img = bg
                out = io.BytesIO()
                img.save(out, format="WEBP", quality=85)
                filename = f"{uuid.uuid4().hex}.webp"
                key = f"{prefix}/remote/{filename}"
                storage = get_storage()
                new_url = storage.save(key, out.getvalue(), "image/webp")
            if old_url:
                try:
                    storage.delete(old_url)
                except Exception:
                    pass
            return new_url
    except Exception as e:
        logger.warning("Failed to save remote %s %s: %s", prefix, image_url, e)
    return image_url


def _save_remote_avatar(avatar_url: str, local_username: str, old_url: str = "") -> str:
    return _save_remote_image(avatar_url, "avatars", local_username, old_url)


def _extract_custom_fields(attachment: list) -> list:
    """Extract PropertyValue entries from remote actor attachment field."""
    import re
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
        import httpx
        headers = {"Accept": "application/activity+json"}
        if sign_as:
            import datetime, time, hashlib, base64
            from app.crypto_utils import sign_string, get_private_key
            from app.config import SECRET_KEY
            from urllib.parse import urlparse
            parsed = urlparse(collection_url)
            date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            headers["Signature"] = f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            headers["Date"] = date
            headers["Host"] = parsed.netloc
        resp = httpx.get(collection_url, headers=headers, timeout=10, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            return int(data.get("totalItems", 0))
    except Exception:
        pass
    return 0


def _get_instance_actor(session) -> User:
    """Get or create the instance actor (system account for server-level requests)."""
    from app.crypto_utils import generate_keypair, encrypt_key
    from app.config import SECRET_KEY
    actor = session.query(User).filter_by(username="actor", is_remote=False).first()
    if not actor:
        priv, pub = generate_keypair()
        actor = User(
            username="actor",
            display_name="(instance actor)",
            password_hash="",
            private_key=encrypt_key(priv, SECRET_KEY),
            public_key=pub,
            is_remote=False,
            is_admin=False,
            role="actor",
        )
        session.add(actor)
        session.commit()
    return actor


def _resolve_actor(actor_url: str, force_refresh: bool = False, sign_as: Optional[User] = None) -> Optional[User]:
    import sys
    with get_session() as session:
        user = session.query(User).filter_by(remote_url=actor_url).first()
        if user and not force_refresh:
            return user
        # Fallback: normalize /@username -> /users/username
        if not user:
            from urllib.parse import urlparse as _up
            p = _up(actor_url)
            if "/@" in p.path:
                alt_url = f"{p.scheme}://{p.netloc}/users/{p.path.split('/@')[-1]}"
                user = session.query(User).filter_by(remote_url=alt_url).first()
                if user and not force_refresh:
                    return user

    data = None
    if sign_as:
        try:
            import datetime, time
            from app.crypto_utils import sign_string, get_private_key
            from urllib.parse import urlparse
            date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
            parsed = urlparse(actor_url)
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            sig_header = f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            headers = {"Accept": "application/activity+json", "Signature": sig_header, "Date": date, "Host": parsed.netloc}
            resp = _safe_fetch(actor_url, timeout=10, headers=headers)
            if resp:
                data = resp.json()
        except Exception:
            pass

    if data is None:
        try:
            resp = _safe_fetch(actor_url, timeout=10, headers={"Accept": "application/activity+json"})
            if resp:
                data = resp.json()
        except Exception:
            pass

    if not data:
        return None


    # Verify the response's id domain matches the requested URL's domain
    resp_id = data.get("id", "")
    canonical_url = resp_id or actor_url
    if resp_id:
        from urllib.parse import urlparse
        req_domain = urlparse(actor_url).hostname or ""
        resp_domain = urlparse(resp_id).hostname or ""
        if req_domain and resp_domain and req_domain != resp_domain:
            logger.warning("Domain mismatch: requested %s, response claims %s", req_domain, resp_domain)
            return None

    preferred_username = data.get("preferredUsername", "")
    if not preferred_username:
        return None

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

    with get_session() as session:
        existing = session.query(User).filter_by(remote_url=actor_url).first()
        base_username_clean = local_username.replace("@", "_")

        if existing:
            existing.public_key = public_key_pem
            existing.display_name = data.get("name", existing.display_name)
            existing.summary = data.get("summary", existing.summary)
            existing.remote_url = canonical_url
            existing.inbox_url = data.get("inbox", existing.inbox_url)
            existing.shared_inbox_url = data.get("endpoints", {}).get("sharedInbox", existing.shared_inbox_url)
            existing.is_locked = data.get("manuallyApprovesFollowers", existing.is_locked)
            existing.profile_url = data.get("url", existing.profile_url or "")
            if avatar_url:
                existing.profile_image = _save_remote_avatar(avatar_url, base_username_clean, existing.profile_image)
            if header_url:
                existing.header_image = _save_remote_image(header_url, "headers", base_username_clean, existing.header_image)
            existing.custom_fields = _extract_custom_fields(data.get("attachment", []))
            _process_emoji_tags(data.get("tag", []), session)
            session.commit()
            return existing

        # Also check by username in case remote_url is missing/stale
        by_username = session.query(User).filter_by(username=local_username).first()
        if by_username:
            by_username.remote_url = canonical_url
            by_username.public_key = public_key_pem or by_username.public_key
            by_username.display_name = data.get("name", by_username.display_name)
            by_username.summary = data.get("summary", by_username.summary)
            by_username.profile_url = data.get("url", by_username.profile_url or "")
            if avatar_url:
                by_username.profile_image = _save_remote_avatar(avatar_url, base_username_clean, by_username.profile_image)
            if header_url:
                by_username.header_image = _save_remote_image(header_url, "headers", base_username_clean, by_username.header_image)
            by_username.custom_fields = _extract_custom_fields(data.get("attachment", []))
            _process_emoji_tags(data.get("tag", []), session)
            session.commit()
            return by_username

        # Ensure uniqueness
        base_username = local_username
        counter = 1
        while session.query(User).filter_by(username=local_username).first():
            local_username = f"{base_username}_{counter}"
            counter += 1

        priv, pub = generate_keypair()
        profile_image = _save_remote_avatar(avatar_url, base_username_clean) if avatar_url else ""
        header_image = _save_remote_image(header_url, "headers", base_username_clean) if header_url else ""
        user = User(
            username=local_username,
            display_name=data.get("name", preferred_username),
            summary=data.get("summary", ""),
            password_hash="remote_user",
            private_key=encrypt_key(priv, SECRET_KEY),
            public_key=public_key_pem or pub,
            is_remote=True,
            remote_url=canonical_url,
            profile_url=data.get("url", ""),
            inbox_url=data.get("inbox", ""),
            shared_inbox_url=data.get("endpoints", {}).get("sharedInbox", ""),
            profile_image=profile_image,
            header_image=header_image,
            is_locked=data.get("manuallyApprovesFollowers", False),
            custom_fields=_extract_custom_fields(data.get("attachment", [])),
            remote_followers_count=_fetch_remote_count(data.get("followers", ""), sign_as),
            remote_following_count=_fetch_remote_count(data.get("following", ""), sign_as),
        )
        session.add(user)
        session.flush()
        _process_emoji_tags(data.get("tag", []), session)
        session.commit()
        return user


def _handle_follow(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    raw_object = activity.get("object", "")
    object_url = raw_object if isinstance(raw_object, str) else raw_object.get("id", "")
    activity_id = activity.get("id", "")

    local_username = _parse_username_from_url(object_url)

    # Resolve follower BEFORE opening session to avoid nested transactions
    with get_session() as s:
        target = s.query(User).filter_by(username=local_username, is_remote=False).first()
    if not target:
        return (404, "Target user not found")

    target_id = target.id
    follower = _resolve_actor(actor_url, sign_as=target)
    if not follower:
        return (404, "Follower not found")

    with get_session() as session:
        target = session.query(User).get(target_id)
        follower = session.merge(follower)
        follower_id = follower.id
        accepted = not target.is_locked
        existing = session.query(Follow).filter_by(
            follower_id=follower.id, following_id=target.id
        ).first()
        if not existing:
            follow = Follow(follower_id=follower.id, following_id=target.id, accepted=accepted, activity_id=activity_id)
            session.add(follow)
            notification = Notification(
                user_id=target.id,
                from_user_id=follower.id,
                notification_type="follow_request" if not accepted else "follow",
            )
            session.add(notification)
            session.commit()
            from app.push import send_push_to_user
            from app.timeline_stream import broadcast_notif_sound
            send_push_to_user(target.id, "follow" if accepted else "follow_request", follower.username)
            broadcast_notif_sound(target.id)

        # Send Accept only if auto-approved (not locked) — inside session so follower is still bound
        if accepted:
            _send_accept(actor_url, activity_id, target, follower=follower)

    return (200, "Followed")


def _send_accept(actor_url: str, activity_id: str, target: User, follower: User = None):
    inbox = follower.inbox_url if follower and follower.inbox_url else (actor_url.rstrip("/") + "/inbox")
    accept = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{target.actor_uri()}#accepts/{activity_id.split('/')[-1]}",
        "type": "Accept",
        "actor": target.actor_uri(),
        "object": {
            "id": activity_id,
            "type": "Follow",
            "actor": actor_url,
            "object": target.actor_uri(),
        },
    }
    _post_to_inbox(inbox, accept, target)


def _send_reject(inbox_url: str, activity_id: str, target: User, follower_actor_url: str = ""):
    reject = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{target.actor_uri()}#rejects/{activity_id.split('/')[-1]}",
        "type": "Reject",
        "actor": target.actor_uri(),
        "object": {
            "id": activity_id,
            "type": "Follow",
            "actor": follower_actor_url or inbox_url,
            "object": target.actor_uri(),
        },
    }
    _post_to_inbox(inbox_url, reject, target)


def _handle_reject(activity: dict) -> tuple[int, str]:
    import sys
    rejecter_url = activity.get("actor", "")
    if isinstance(rejecter_url, list):
        rejecter_url = rejecter_url[0]

    obj = activity.get("object", {})
    follower_url = obj.get("actor", "") if isinstance(obj, dict) else ""

    with get_session() as session:
        remote_user = session.query(User).filter_by(remote_url=rejecter_url).first()
        if not remote_user:
            return (200, "OK")

        local_user = None
        if follower_url:
            local_username = _parse_username_from_url(follower_url)
            if local_username:
                local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()

        query_filter = {
            "following_id": remote_user.id,
            "accepted": False
        }
        if local_user:
            query_filter["follower_id"] = local_user.id

        follow_rel = session.query(Follow).filter_by(**query_filter).first()
        
        if not follow_rel:
            return (200, "No pending follow request found")

        local_user = session.query(User).get(follow_rel.follower_id)
        local_user_id = local_user.id
        session.query(Notification).filter_by(
            from_user_id=remote_user.id, user_id=local_user.id,
            notification_type="follow_request",
        ).delete()
        session.delete(follow_rel)
        session.commit()

    from app.timeline_stream import broadcast_refresh_notifs
    broadcast_refresh_notifs(local_user_id)
    return (200, "Rejected follow removed")

def _handle_accept(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    if isinstance(obj, dict):
        follower_url = obj.get("actor", "")
    elif isinstance(obj, str):
        try:
            resp = httpx.get(obj, headers={"Accept": "application/activity+json"}, timeout=10)
            if resp.status_code == 200:
                follow_activity = resp.json()
                follower_url = follow_activity.get("actor", "")
        except Exception:
            pass
    else:
        follower_url = ""

    if not follower_url:
        return (200, "OK")

    accepter_url = activity.get("actor", "")
    if isinstance(accepter_url, list):
        accepter_url = accepter_url[0]

    local_username = _parse_username_from_url(follower_url)
    if not local_username:
        return (200, "OK")

    with get_session() as session:
        local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
        if not local_user:
            return (200, "OK")

        remote_accepter = _resolve_actor(accepter_url)
        if not remote_accepter:
            return (200, "OK")

        remote_accepter_id = remote_accepter.id
        follow_rel = session.query(Follow).filter_by(
            follower_id=local_user.id,
            following_id=remote_accepter_id,
            accepted=False,
        ).first()
        if not follow_rel:
            return (200, "No pending follow request found")
        if follow_rel:
            follow_rel.accepted = True
            session.commit()

    return (200, "Accepted follow")


def _fetch_remote_post(url: str, signer: User, session, _depth=0):
    """Fetch a remote AP object and save it as a Post. Returns the Post or None."""
    if _depth > 3 or not url:
        return None

    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(url)
    headers = {"Accept": "application/activity+json"}

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
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
    except Exception:
        pass

    if data is None and signer:
        try:
            resp = httpx.get(url, headers={"Accept": "application/activity+json"}, timeout=15, follow_redirects=True)
            if resp.status_code == 200:
                data = resp.json()
        except Exception:
            pass

    if data is None:
        return None

    obj = data.get("object", data) if isinstance(data, dict) else {}
    if not isinstance(obj, dict):
        return None
    obj_type = obj.get("type", "")
    if obj_type not in ("Note", "Question"):
        return None

    ap_id = obj.get("id", url)
    existing = session.query(Post).filter_by(ap_id=ap_id).first()
    if existing and not existing.is_deleted:
        return existing

    attributed_to = obj.get("attributedTo", "")
    if isinstance(attributed_to, list):
        attributed_to = attributed_to[0] if attributed_to else ""
    if isinstance(attributed_to, dict):
        attributed_to = attributed_to.get("id", "")
    if not attributed_to:
        return None

    _resolve_actor(attributed_to)
    author = session.query(User).filter_by(remote_url=attributed_to).first()
    if not author:
        return None

    raw_content = obj.get("content", "") or ""
    if len(raw_content) > 65536:
        raw_content = raw_content[:65536]
    content = _normalize_mentions(_sanitize_html(raw_content))
    summary = obj.get("summary", "")

    to = obj.get("to", [])
    if isinstance(to, str): to = [to]
    cc = obj.get("cc", [])
    if isinstance(cc, str): cc = [cc]
    all_auds = to + cc
    pub = "https://www.w3.org/ns/activitystreams#Public"
    if pub in to:
        vis = "public"
    elif pub in cc:
        vis = "home"
    elif any(a.endswith("/followers") for a in all_auds):
        vis = "followers"
    elif all(a.startswith("http") for a in all_auds if a):
        vis = "mention"
    else:
        vis = "home"

    in_reply_to_ap = obj.get("inReplyTo", "")
    if isinstance(in_reply_to_ap, dict):
        in_reply_to_ap = in_reply_to_ap.get("id", "")

    in_reply_to_id = None
    if in_reply_to_ap:
        parent = session.query(Post).filter_by(ap_id=in_reply_to_ap).first()
        if parent:
            in_reply_to_id = parent.id
        else:
            parent = _fetch_remote_post(in_reply_to_ap, signer, session, _depth + 1)
            if parent:
                in_reply_to_id = parent.id

    mentioned_names = set(re.findall(r'@(\w+(?:@[\w.-]+)?)', content or ""))
    mentioned_ids = []
    if mentioned_names:
        users = session.query(User).filter(User.username.in_(mentioned_names)).all()
        mentioned_ids = [u.id for u in users]

    _process_emoji_tags(obj.get("tag", []), session)
    session.flush()

    raw_attachments = obj.get("attachment", [])
    media_list = []
    if isinstance(raw_attachments, list):
        for att in raw_attachments:
            if not isinstance(att, dict):
                continue
            att_type = att.get("mediaType", "")
            att_url = ""
            if isinstance(att.get("url"), str):
                att_url = att["url"]
            elif isinstance(att.get("url"), dict):
                att_url = att["url"].get("href", "")
            if not att_url:
                continue
            cached = _cache_remote_media(att_url)
            if att_type.startswith("image/"):
                media_list.append({"url": cached, "type": "image"})
            elif att_type.startswith("video/"):
                media_list.append({"url": cached, "type": "video"})

    post = Post(
        author_id=author.id,
        content=content,
        summary=summary,
        visibility=vis,
        ap_id=ap_id,
        in_reply_to_ap_id=in_reply_to_ap,
        in_reply_to_id=in_reply_to_id,
        mentioned_user_ids=mentioned_ids,
        media_attachments=media_list if media_list else None,
        is_sensitive=obj.get("sensitive", False),
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
    return post


def _handle_create(activity: dict) -> tuple[int, str]:
    import sys, json
    obj = activity.get("object", {})
    obj_type = obj.get("type") if isinstance(obj, dict) else ""
    if obj_type in ("Note", "Question"):
        raw_actor = activity.get("actor")
        if not raw_actor:
            return (400, "Missing actor")
        actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
        # Try with sign_as from the poll author (for vote on our poll)
        in_reply_to_url = obj.get("inReplyTo", "") if isinstance(obj, dict) else ""
        _sign_as = None
        if in_reply_to_url:
            with get_session() as __s:
                _poll = __s.query(Post).filter_by(ap_id=in_reply_to_url).first()
                if _poll:
                    _sign_as = __s.query(User).get(_poll.author_id)
        actor = _resolve_actor(actor_url, sign_as=_sign_as)
        if not actor:
            return (404, "Actor not found")
        actor_id = actor.id
        actor_username = actor.username
        actor_uri = actor.actor_uri()
        actor_remote_url = actor.remote_url or ""


        # Verify attributedTo matches activity actor
        obj_attributed = obj.get("attributedTo", "")
        if isinstance(obj_attributed, list):
            obj_attributed = obj_attributed[0] if obj_attributed else ""
        if isinstance(obj_attributed, dict):
            obj_attributed = obj_attributed.get("id", "")
        if obj_attributed and obj_attributed != actor_url and obj_attributed != actor_uri and obj_attributed != actor_remote_url:
            return (403, "attributedTo does not match actor")

        # Limit content length (65536 chars ~ 64KB)
        raw_content = obj.get("content", "") or ""
        if len(raw_content) > 65536:
            raw_content = raw_content[:65536]
        post_id = obj.get("id", "")
        content = _normalize_mentions(_sanitize_html(raw_content))
        summary = obj.get("summary", "")
        in_reply_to = obj.get("inReplyTo", "")

        # Determine visibility from to/cc
        to = obj.get("to", [])
        if isinstance(to, str):
            to = [to]
        cc = obj.get("cc", [])
        if isinstance(cc, str):
            cc = [cc]
        all_audiences = to + cc
        public_uri = "https://www.w3.org/ns/activitystreams#Public"

        is_incoming_dm = False
        if public_uri in to:
            visibility = "public"
        elif public_uri in cc:
            visibility = "home"
        elif any(aud.endswith("/followers") for aud in all_audiences):
            visibility = "followers"
        elif all_audiences and all(aud.startswith("http") for aud in all_audiences if aud):
            visibility = "mention"
            is_incoming_dm = True
        else:
            visibility = "home"

        # Extract poll data from Question type
        poll_data = None
        if obj_type == "Question":
            options = []
            one_of = obj.get("oneOf") or obj.get("anyOf") or []
            if isinstance(one_of, list):
                for opt in one_of:
                    if isinstance(opt, dict) and opt.get("name"):
                        replies = opt.get("replies", {})
                        votes_count = 0
                        if isinstance(replies, dict):
                            votes_count = replies.get("totalItems", 0)
                        options.append({"text": opt["name"], "votes_count": votes_count})
            if options:
                expires_at = obj.get("endTime") or ""
                poll_data = {
                    "options": options,
                    "expires_at": expires_at,
                }

        with get_session() as session:
            import sys; sys.stdout.flush()
            existing = session.query(Post).filter_by(ap_id=post_id).first()
            import sys; sys.stdout.flush()
            if existing:
                # If the existing post is a poll and incoming has updated votes, update it
                if existing.poll_data and poll_data:
                    for new_opt in poll_data.get("options", []):
                        for old_opt in existing.poll_data.get("options", []):
                            if old_opt.get("text") == new_opt.get("text"):
                                old_opt["votes_count"] = new_opt.get("votes_count", 0)
                                break
                    existing.poll_data["expires_at"] = poll_data.get("expires_at", existing.poll_data.get("expires_at", ""))
                    session.commit()
                    return (200, "Poll votes updated")
                return (200, "Already exists")

            reply_to_post = None
            if in_reply_to:
                reply_to_post = session.query(Post).filter_by(ap_id=in_reply_to).first()
                if not reply_to_post:
                    alt_url = in_reply_to.replace("https://", "http://") if "https://" in in_reply_to else in_reply_to.replace("http://", "https://")
                    reply_to_post = session.query(Post).filter_by(ap_id=alt_url).first()
                if not reply_to_post:
                    _local_signer = session.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == actor_id, User.is_remote == False).first()
                    if not _local_signer:
                        _local_signer = _get_instance_actor(session)
                    reply_to_post = _fetch_remote_post(in_reply_to, _local_signer, session)
                    if reply_to_post:
                        try:
                            from app.timeline_stream import broadcast_post
                            _ra = reply_to_post.author
                            broadcast_post({
                                "id": reply_to_post.id,
                                "number": reply_to_post.number or "",
                                "content": reply_to_post.content,
                                "summary": reply_to_post.summary or "",
                                "visibility": reply_to_post.visibility or "public",
                                "created_at": reply_to_post.created_at.isoformat() if reply_to_post.created_at else "",
                                "author": {
                                    "id": _ra.id, "username": _ra.username,
                                    "display_name": _ra.display_name or _ra.username,
                                    "avatar": _ra.profile_image or "", "header": _ra.header_image or "",
                                    "summary": _ra.summary or "", "is_admin": _ra.is_admin,
                                    "is_locked": getattr(_ra, "is_locked", False),
                                    "is_limited": getattr(_ra, "is_limited", False),
                                    "is_remote": _ra.is_remote, "ap_id": _ra.remote_url or "",
                                },
                                "likes_count": 0, "boosts_count": 0, "replies_count": 0,
                                "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                                "is_dm": False, "is_sensitive": getattr(reply_to_post, "is_sensitive", False) or False,
                                "ap_id": reply_to_post.ap_id or "", "media_attachments": reply_to_post.media_attachments or [],
                                "poll_data": reply_to_post.poll_data, "my_vote": None, "reactions": {}, "my_reaction": None,
                            }, reply_to_post.author_id, reply_to_post.visibility or "public", False)
                        except Exception:
                            pass

            # Mastodon poll votes: Create(Note) with name + inReplyTo + no content
            vote_name = obj.get("name", "") if not raw_content.strip() else ""
            if vote_name and reply_to_post and reply_to_post.poll_data:
                poll_post = reply_to_post
                options = poll_post.poll_data.get("options", [])
                option_idx = -1
                for i, opt in enumerate(options):
                    if opt.get("text", "").strip().lower() == vote_name.strip().lower():
                        option_idx = i
                        break
                if option_idx >= 0:
                    expires_at = poll_post.poll_data.get("expires_at")
                    if expires_at:
                        try:
                            exp = datetime.datetime.fromisoformat(expires_at)
                            now = datetime.datetime.now(datetime.timezone.utc)
                            if exp < now:
                                return (200, "Poll ended")
                        except (ValueError, TypeError) as ex:
                            pass
                    existing_vote = session.query(Vote).filter_by(user_id=actor_id, post_id=poll_post.id).first()
                    if existing_vote:
                        if existing_vote.option_index == option_idx:
                            return (200, "Already voted")
                        options[existing_vote.option_index]["votes_count"] = max(0, options[existing_vote.option_index].get("votes_count", 0) - 1)
                        existing_vote.option_index = option_idx
                    else:
                        session.add(Vote(user_id=actor_id, post_id=poll_post.id, option_index=option_idx))
                    import copy
                    new_options = copy.deepcopy(options)
                    new_options[option_idx]["votes_count"] = new_options[option_idx].get("votes_count", 0) + 1
                    poll_post.poll_data = {**poll_post.poll_data, "options": new_options}
                    session.commit()
                    from app.timeline_stream import broadcast_post, broadcast_refresh_notifs
                    # Notify poll author + all voters
                    _voter_ids = {v.user_id for v in session.query(Vote).filter_by(post_id=poll_post.id).all()}
                    _voter_ids.add(poll_post.author_id)
                    for _vid in _voter_ids:
                        broadcast_refresh_notifs(_vid)
                    if poll_post.author_id != actor_id:
                        from app.push import send_push_to_user
                        from app.timeline_stream import broadcast_notif_sound
                        send_push_to_user(poll_post.author_id, "vote", actor_username, poll_post.id)
                        broadcast_notif_sound(poll_post.author_id)
                    broadcast_post({
                        "id": poll_post.id,
                        "type": "update",
                        "poll_data": poll_post.poll_data,
                    }, poll_post.author_id, poll_post.visibility or "public", False)
                    return (200, "Voted")

            # Parse mentioned users from content
            mentioned_names = set(re.findall(r'@(\w+(?:@[\w.-]+)?)', content or ""))
            mentioned_hrefs = set()
            # Also parse mentions from AP tag array
            for tag in (obj.get("tag", []) or []):
                if isinstance(tag, dict) and tag.get("type") == "Mention":
                    href = tag.get("href", "")
                    name = tag.get("name", "")
                    if href:
                        mentioned_hrefs.add(href.rstrip("/"))
                    if name and name.startswith("@"):
                        mentioned_names.add(name.lstrip("@"))
            # Also check `to` / `cc` for local user actor URIs (DMs from Mastodon)
            for _aud in all_audiences:
                _a = _aud.rstrip("/")
                if _a and _a.startswith("http"):
                    mentioned_hrefs.add(_a)
            mentioned_ids = []
            _seen_ids = set()
            if mentioned_names:
                for _name in mentioned_names:
                    if '@' in _name:
                        _lp, _dom = _name.split('@', 1)
                        u = session.query(User).filter(
                            User.username == _lp, User.is_remote == True,
                        ).first()
                        if u and u.id not in _seen_ids and u.remote_url:
                            from urllib.parse import urlparse as _urlparse
                            _p = _urlparse(u.remote_url)
                            if _p.hostname and _p.hostname.lower() == _dom.lower():
                                mentioned_ids.append(u.id)
                                _seen_ids.add(u.id)
                    else:
                        u = session.query(User).filter(User.username == _name).first()
                        if u and u.id not in _seen_ids:
                            mentioned_ids.append(u.id)
                            _seen_ids.add(u.id)
            if mentioned_hrefs:
                for _href in mentioned_hrefs:
                    u = session.query(User).filter(User.remote_url == _href).first()
                    if u and u.id not in _seen_ids:
                        mentioned_ids.append(u.id)
                        _seen_ids.add(u.id)
                    if u is None and BASE_URL in _href:
                        for _u in session.query(User).filter_by(is_remote=False).all():
                            if (_u.actor_uri() == _href or _u.actor_uri().replace("/users/", "/@") == _href) and _u.id not in _seen_ids:
                                mentioned_ids.append(_u.id)
                                _seen_ids.add(_u.id)
                                break

            # Check if actor's domain is server-muted
            actor_domain = urlparse(actor.remote_url).hostname if actor.remote_url else ""
            if actor_domain:
                mute_entry = session.query(MutedServer).filter_by(domain=actor_domain).first()
                if mute_entry and mute_entry.muted and visibility == "public":
                    visibility = "home"

            # Process custom emoji tags
            _process_emoji_tags(obj.get("tag", []), session)
            session.flush()

            import json as _json
            raw_attachments = obj.get("attachment", []) if isinstance(obj, dict) else []
            media_list = []
            if isinstance(raw_attachments, list):
                for att in raw_attachments:
                    if not isinstance(att, dict):
                        continue
                    att_type = att.get("mediaType", "")
                    url = ""
                    if isinstance(att.get("url"), str):
                        url = att["url"]
                    elif isinstance(att.get("url"), dict):
                        url = att["url"].get("href", "")
                    if not url:
                        continue
                    cached = _cache_remote_media(url)
                    if att_type.startswith("image/"):
                        media_list.append({"url": cached, "type": "image"})
                    elif att_type.startswith("video/"):
                        media_list.append({"url": cached, "type": "video"})

            post = Post(
                author_id=actor_id,
                content=content,
                summary=summary,
                visibility=visibility,
                mentioned_user_ids=mentioned_ids,
                ap_id=post_id,
                in_reply_to_ap_id=in_reply_to,
                in_reply_to_id=reply_to_post.id if reply_to_post else None,
                media_attachments=media_list if media_list else None,
                poll_data=poll_data,
                is_dm=is_incoming_dm,
                is_sensitive=obj.get("sensitive", False),
            )
            session.add(post)
            session.flush()

            # Notify local users mentioned or replied to
            _notified = set()
            if reply_to_post and reply_to_post.author_id != actor_id:
                _notified.add(reply_to_post.author_id)
                session.add(Notification(
                    user_id=reply_to_post.author_id,
                    from_user_id=actor_id,
                    notification_type="mention",
                    post_id=post.id,
                ))
            for _mu_id in mentioned_ids:
                if _mu_id != actor_id and _mu_id not in _notified:
                    _notified.add(_mu_id)
                    session.add(Notification(
                        user_id=_mu_id, from_user_id=actor_id,
                        notification_type="mention", post_id=post.id,
                    ))

            # Notify local followers who enabled post notifications (skip self + already notified)
            followers = session.query(Follow).filter(
                Follow.following_id == actor_id,
                Follow.notify_on_post == True,
            ).all()
            for f in followers:
                if not f.follower.is_remote and f.follower.id != actor_id and f.follower.id not in _notified:
                    _notified.add(f.follower.id)
                    session.add(Notification(
                        user_id=f.follower.id,
                        from_user_id=actor_id,
                        notification_type="post",
                        post_id=post.id,
                    ))

            session.commit()
            from app.push import send_push_to_user
            from app.timeline_stream import broadcast_notif_sound
            _push_notified = set()
            if reply_to_post and reply_to_post.author_id != actor_id and reply_to_post.author_id not in _push_notified:
                _push_notified.add(reply_to_post.author_id)
                send_push_to_user(reply_to_post.author_id, "mention", actor_username, post.id)
                broadcast_notif_sound(reply_to_post.author_id)
            for _mu_id in mentioned_ids:
                if _mu_id != actor_id and _mu_id not in _push_notified:
                    _push_notified.add(_mu_id)
                    send_push_to_user(_mu_id, "mention", actor_username, post.id)
                    broadcast_notif_sound(_mu_id)
            for f in followers:
                if not f.follower.is_remote and f.follower.id != actor_id and f.follower.id not in _push_notified:
                    _push_notified.add(f.follower.id)
                    send_push_to_user(f.follower.id, "post", actor_username, post.id)
                    broadcast_notif_sound(f.follower.id)
            from app.timeline_stream import broadcast_refresh_notifs
            broadcast_refresh_notifs()
            try:
                from app.eventbus import broadcast
                broadcast("new_post", {"post_id": post.id, "author_id": actor_id})
            except Exception as e:
                logger.warning("broadcast failed: %s", e)
            try:
                from app.timeline_stream import broadcast_post
                author = post.author
                post_json = {
                    "id": post.id,
                    "number": post.number or "",
                    "content": post.content,
                    "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": post.created_at.isoformat() if post.created_at else "",
                    "author": {
                        "id": author.id,
                        "username": author.username,
                        "display_name": author.display_name or author.username,
                        "avatar": author.profile_image or "",
                        "header": author.header_image or "",
                        "summary": author.summary or "",
                        "is_admin": author.is_admin,
                        "is_locked": getattr(author, 'is_locked', False),
                        "is_limited": getattr(author, 'is_limited', False),
                        "is_remote": author.is_remote,
                        "ap_id": author.remote_url or "",
                    },
                    "likes_count": 0,
                    "boosts_count": 0,
                    "replies_count": 0,
                    "liked": False,
                    "boosted": False,
                    "bookmarked": False,
                    "is_mine": False,
                    "is_dm": is_incoming_dm,
                    "is_sensitive": getattr(post, 'is_sensitive', False) or False,
                    "ap_id": post.ap_id or "",
                    "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data,
                    "my_vote": None,
                    "reactions": {},
                    "my_reaction": None,
                }
                broadcast_post(post_json, actor_id, visibility, is_incoming_dm)
            except Exception as e:
                logger.warning("timeline broadcast failed: %s", e)

        return (200, "Created")
    return (200, "OK")


def _build_reactions(session, post_id: int) -> dict:
    """Build reactions dict from Like table for a given post."""
    from app.models import Like as _Like
    from sqlalchemy import func as _func
    _reactions = {}
    _default_react = "★"
    for _pid, _react, _cnt in session.query(_Like.post_id, _func.coalesce(_Like.reaction, _default_react), _func.count(_Like.id)).filter(
        _Like.post_id == post_id
    ).group_by(_Like.post_id, _Like.reaction).all():
        if _pid not in _reactions:
            _reactions[_pid] = {}
        _reactions[_pid][_react] = _cnt
    return _reactions.get(post_id, {})


def _handle_like(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    object_url = activity["object"] if isinstance(activity.get("object"), str) else ""
    activity_id = activity.get("id", "")
    reaction = activity.get("_misskey_reaction", activity.get("reaction", ""))

    if not object_url:
        return (200, "OK")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        _sign_as = session.query(User).get(post.author_id) if post else None
    actor = _resolve_actor(actor_url, sign_as=_sign_as)
    if not actor:
        return (404, "Actor not found")

    actor_id = actor.id
    actor_username = actor.username

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if not post:
            return (200, "OK")

        # Process remote emoji if present in tag array
        print(f"[EMOJI] reaction='{reaction}' startswith(:)={reaction.startswith(':') if reaction else False}", flush=True)
        if reaction and reaction.startswith(":") and reaction.endswith(":"):
            _kw = reaction[1:-1]
            print(f"[EMOJI] keyword='{_kw}'", flush=True)
            _existing_emoji = session.query(CustomEmoji).filter_by(keyword=_kw).first()
            print(f"[EMOJI] existing={_existing_emoji.id if _existing_emoji else None}", flush=True)
            if not _existing_emoji:
                tags = activity.get("tag", []) or []
                print(f"[EMOJI] tags count={len(tags)}", flush=True)
                for _i, _tag in enumerate(tags):
                    print(f"[EMOJI] tag[{_i}]: type={_tag.get('type') if isinstance(_tag, dict) else type(_tag).__name__}", flush=True)
                    if isinstance(_tag, dict) and _tag.get("type") == "Emoji":
                        _icon = _tag.get("icon", {})
                        _url = _icon.get("url", "") if isinstance(_icon, dict) else ""
                        _tag_id = _tag.get("id", "")
                        _domain = urlparse(_tag_id).netloc if _tag_id else ""
                        print(f"[EMOJI] found Emoji tag: name={_tag.get('name')} url={_url} domain={_domain}", flush=True)
                        if _url:
                            from app.utils.storage import get_storage
                            _storage = get_storage()
                            try:
                                import httpx as _httpx
                                print(f"[EMOJI] downloading {_url}", flush=True)
                                _resp = _httpx.get(_url, timeout=10)
                                print(f"[EMOJI] download status={_resp.status_code} size={len(_resp.content)}", flush=True)
                                if _resp.status_code == 200:
                                    _ext = _url.rsplit(".", 1)[-1].split("?")[0] if "." in _url else "png"
                                    _fname = f"{_kw}.{_ext}"
                                    _storage.save(f"emojis/remote/{_fname}", _resp.content, f"image/{_ext}")
                                    session.add(CustomEmoji(keyword=_kw, file_name=_fname, category="remote", domain=_domain))
                                    session.flush()
                                    print(f"[EMOJI] saved: {_fname}", flush=True)
                                    logger.info("Imported remote emoji: %s from %s", _kw, _domain)
                            except Exception as e:
                                print(f"[EMOJI] error: {e}", flush=True)
                                logger.warning("Failed to import remote emoji %s: %s", _kw, e)
                        break

        existing = session.query(Like).filter_by(user_id=actor_id, post_id=post.id).first()
        if existing:
            if reaction and existing.reaction != reaction:
                existing.reaction = reaction
                session.commit()
            return (200, "Already liked")

        like_ap_id = activity_id
        if not like_ap_id:
            like_ap_id = f"{BASE_URL}/likes/{uuid.uuid4()}"

        like = Like(
            user_id=actor_id,
            post_id=post.id,
            ap_id=like_ap_id,
            reaction=reaction if reaction else None,
        )
        session.add(like)

        existing_n = session.query(Notification).filter_by(
            user_id=post.author_id, from_user_id=actor_id, notification_type="like", post_id=post.id
        ).first()
        if not existing_n:
            n = Notification(
                user_id=post.author_id,
                from_user_id=actor_id,
                notification_type="like",
                post_id=post.id,
            )
            session.add(n)
            session.commit()
            from app.push import send_push_to_user
            from app.timeline_stream import broadcast_notif_sound, broadcast_post, broadcast_refresh_notifs as _brn
            send_push_to_user(post.author_id, "like", actor_username, post.id)
            broadcast_notif_sound(post.author_id)
            _brn(post.author_id)
            # Broadcast updated reactions to timeline
            import json as _js, datetime as _dt
            try:
                _la = post.author
                broadcast_post({
                    "id": post.id, "type": "update",
                    "number": post.number or "",
                    "content": post.content, "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": post.created_at.isoformat() if post.created_at else "",
                    "author": {
                        "id": _la.id, "username": _la.username,
                        "display_name": _la.display_name or _la.username,
                        "avatar": _la.profile_image or "", "header": _la.header_image or "",
                        "summary": _la.summary or "", "is_admin": _la.is_admin,
                        "is_locked": getattr(_la, "is_locked", False),
                        "is_limited": getattr(_la, "is_limited", False),
                        "is_remote": _la.is_remote, "ap_id": _la.remote_url or "",
                    },
                    "likes_count": session.query(Like).filter_by(post_id=post.id).count(),
                    "boosts_count": session.query(Boost).filter_by(post_id=post.id).count(),
                    "replies_count": session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                    "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                    "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data, "my_vote": None, "reactions": {}, "my_reaction": None,
                }, post.author_id, post.visibility or "public", False)
            except Exception:
                pass
        else:
            session.commit()

    return (200, "Liked")


def _handle_vote(activity: dict) -> tuple[int, str]:
    import sys
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    object_url = activity.get("object", "")
    if isinstance(object_url, dict):
        object_url = object_url.get("id", "")
    if not object_url:
        return (200, "OK")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        _sign_as = session.query(User).get(post.author_id) if post else None
    actor = _resolve_actor(actor_url, sign_as=_sign_as)
    if not actor:
        return (404, "Actor not found")

    actor_id = actor.id

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if not post or not post.poll_data:
            return (200, "OK")

        # Determine which option was voted for
        option_name = activity.get("name", "")
        options = post.poll_data.get("options", [])
        option_idx = -1
        if option_name:
            for i, opt in enumerate(options):
                if opt.get("text", "").strip().lower() == option_name.strip().lower():
                    option_idx = i
                    break
        if option_idx < 0 or option_idx >= len(options):
            return (200, "OK")

        # Check if poll expired
        expires_at = post.poll_data.get("expires_at")
        if expires_at:
            try:
                if datetime.datetime.fromisoformat(expires_at) < datetime.datetime.now(datetime.timezone.utc):
                    return (200, "Poll ended")
            except (ValueError, TypeError):
                pass

        # Check for existing vote (change or dedup)
        existing = session.query(Vote).filter_by(user_id=actor_id, post_id=post.id).first()
        if existing:
            if existing.option_index == option_idx:
                return (200, "Already voted")
            options[existing.option_index]["votes_count"] = max(0, options[existing.option_index].get("votes_count", 0) - 1)
            existing.option_index = option_idx
        else:
            session.add(Vote(user_id=actor_id, post_id=post.id, option_index=option_idx))

        options[option_idx]["votes_count"] = options[option_idx].get("votes_count", 0) + 1
        post.poll_data = {**post.poll_data, "options": options}
        session.commit()

    return (200, "Voted")


def _handle_announce(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    object_url = activity["object"] if isinstance(activity.get("object"), str) else ""
    activity_id = activity.get("id", "")

    if not object_url:
        return (200, "OK")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        _sign_as = session.query(User).get(post.author_id) if post else None
    actor = _resolve_actor(actor_url, sign_as=_sign_as)
    if not actor:
        return (404, "Actor not found")

    actor_id = actor.id
    actor_username = actor.username

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if not post:
            _local_signer = session.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == actor_id, User.is_remote == False).first()
            if not _local_signer:
                _local_signer = session.query(User).filter_by(is_remote=False).first()
            try:
                post = _fetch_remote_post(object_url, _local_signer, session)
            except Exception as e:
                logger.warning("Announce: _fetch_remote_post failed for %s: %s", object_url, e)
                post = None
            if not post:
                logger.warning("Announce: could not fetch remote post %s", object_url)
                return (200, "OK")

        existing = session.query(Boost).filter_by(user_id=actor_id, post_id=post.id).first()
        if existing:
            return (200, "Already boosted")

        boost_ap_id = activity_id
        if not boost_ap_id:
            boost_ap_id = f"{BASE_URL}/boosts/{uuid.uuid4()}"

        boost = Boost(
            user_id=actor_id,
            post_id=post.id,
            ap_id=boost_ap_id,
        )
        session.add(boost)
        # Create boost pointer post row
        boost_post = Post(
            author_id=actor_id,
            content="",
            boost_of_id=post.id,
            visibility=post.visibility or "public",
        )
        session.add(boost_post)

        existing_n = session.query(Notification).filter_by(
            user_id=post.author_id, from_user_id=actor_id, notification_type="boost", post_id=post.id
        ).first()
        if not existing_n:
            n = Notification(
                user_id=post.author_id,
                from_user_id=actor_id,
                notification_type="boost",
                post_id=post.id,
            )
            session.add(n)
            session.commit()
            from app.push import send_push_to_user
            from app.timeline_stream import broadcast_notif_sound
            send_push_to_user(post.author_id, "boost", actor_username, post.id)
            broadcast_notif_sound(post.author_id)
        else:
            session.commit()

        try:
            from app.timeline_stream import broadcast_post
            _a = post.author
            broadcast_post({
                "id": post.id,
                "number": post.number or "",
                "content": post.content,
                "summary": post.summary or "",
                "visibility": post.visibility or "public",
                "created_at": post.created_at.isoformat() if post.created_at else "",
                "author": {
                    "id": _a.id, "username": _a.username,
                    "display_name": _a.display_name or _a.username,
                    "avatar": _a.profile_image or "", "header": _a.header_image or "",
                    "summary": _a.summary or "", "is_admin": _a.is_admin,
                    "is_locked": getattr(_a, "is_locked", False),
                    "is_limited": getattr(_a, "is_limited", False),
                    "is_remote": _a.is_remote, "ap_id": _a.remote_url or "",
                },
                "likes_count": session.query(Like).filter_by(post_id=post.id).count(),
                "boosts_count": session.query(Boost).filter_by(post_id=post.id).count(),
                "replies_count": session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                "poll_data": post.poll_data, "my_vote": None,
                "reactions": _build_reactions(session, post.id),
                "my_reaction": None,
            }, post.author_id, post.visibility or "public", False)
        except Exception:
            pass

    return (200, "Announced")

def _handle_block(activity: dict) -> tuple[int, str]:
    import sys as _sys
    actor_url = activity.get("actor", "")
    object_url = activity.get("object", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    if isinstance(object_url, dict):
        object_url = object_url.get("id", "")
    print(f"[BLOCK] received: actor={actor_url} object={object_url}", flush=True)

    # Try to resolve with a local user's signature to ensure remote server accepts
    local_username = _parse_username_from_url(object_url)
    print(f"[BLOCK] parsed local_username={local_username}", flush=True)
    sign_as = None
    if local_username:
        with get_session() as _s:
            _u = _s.query(User).filter_by(username=local_username, is_remote=False).first()
            if _u:
                sign_as = _u
                print(f"[BLOCK] sign_as user={_u.username} id={_u.id}", flush=True)
            else:
                print(f"[BLOCK] local user '{local_username}' not found in DB", flush=True)
    remote_user = _resolve_actor(actor_url, sign_as=sign_as)
    print(f"[BLOCK] _resolve_actor returned: {remote_user.id if remote_user else None}", flush=True)
    if not remote_user:
        print(f"[BLOCK] could not resolve remote actor, returning OK", flush=True)
        return (200, "OK")

    try:
        with get_session() as session:
            # Re-query both users in the SAME session to avoid detached instance issues
            remote = session.query(User).filter_by(remote_url=actor_url).first()
            if not remote:
                from urllib.parse import urlparse as _up
                p = _up(actor_url)
                if "/@" in p.path:
                    alt_url = f"{p.scheme}://{p.netloc}/users/{p.path.split('/@')[-1]}"
                    remote = session.query(User).filter_by(remote_url=alt_url).first()
            if not remote:
                remote = session.query(User).filter_by(id=remote_user.id).first()
            if not remote:
                print(f"[BLOCK] remote user not found in DB", flush=True)
                return (200, "OK")
            print(f"[BLOCK] remote user id={remote.id} username={remote.username}", flush=True)
            local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
            if not local_user:
                print(f"[BLOCK] local user not found", flush=True)
                return (200, "OK")
            print(f"[BLOCK] local user id={local_user.id}", flush=True)
            deleted_incoming = session.query(Follow).filter_by(follower_id=remote.id, following_id=local_user.id).delete()
            deleted_outgoing = session.query(Follow).filter_by(follower_id=local_user.id, following_id=remote.id).delete()
            existing = session.query(UserBlock).filter_by(user_id=remote.id, target_user_id=local_user.id).first()
            if not existing:
                session.add(UserBlock(user_id=remote.id, target_user_id=local_user.id))
                session.commit()
                print(f"[BLOCK] created UserBlock remote={remote.id} -> local={local_user.id}, deleted follows: in={deleted_incoming} out={deleted_outgoing}", flush=True)
            else:
                print(f"[BLOCK] UserBlock already exists", flush=True)
        return (200, "Blocked")
    except Exception as e:
        import traceback
        print(f"[BLOCK] EXCEPTION: {e}", flush=True)
        traceback.print_exc()
        logger.error("Error processing Block from %s: %s", actor_url, e)
        return (200, "OK")


def _handle_undo(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    obj_type = obj.get("type", "") if isinstance(obj, dict) else ""

    if not isinstance(obj, dict) and isinstance(obj, str):
        fetched = None
        try:
            import httpx
            resp = httpx.get(obj, headers={"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}, follow_redirects=True, timeout=10)
            if resp.status_code < 300:
                fetched = resp.json()
                obj_type = fetched.get("type", "")
        except Exception:
            pass
        if fetched:
            obj = fetched
        else:
            return (200, "OK")

    if obj_type == "Follow":
        actor_url = obj.get("actor", activity.get("actor", ""))
        object_url = obj.get("object", "")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]

        local_username = _parse_username_from_url(object_url)
        with get_session() as session:
            target = session.query(User).filter_by(username=local_username, is_remote=False).first()
            if not target:
                return (200, "OK")
            follower = _resolve_actor(actor_url)
            if not follower:
                return (200, "OK")
            follower_id = follower.id
            session.query(Follow).filter_by(
                follower_id=follower_id, following_id=target.id
            ).delete()
            session.commit()
            from app.timeline_stream import broadcast_refresh_notifs
            broadcast_refresh_notifs(target.id)

        return (200, "Unfollowed")

    elif obj_type == "Like":
        actor_url = activity.get("actor", "")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]
        object_url = obj.get("object", "") if isinstance(obj, dict) else ""

        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if post:
                _sign_as = session.query(User).get(post.author_id)
            else:
                _sign_as = None
        actor = _resolve_actor(actor_url, sign_as=_sign_as)
        if not actor:
            return (200, "OK")

        actor_id = actor.id
        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if not post:
                return (200, "OK")
            session.query(Like).filter_by(user_id=actor_id, post_id=post.id).delete()
            session.query(Notification).filter_by(
                user_id=post.author_id, from_user_id=actor_id,
                notification_type="like", post_id=post.id,
            ).delete()
            session.commit()
            from app.timeline_stream import broadcast_refresh_notifs, broadcast_post
            broadcast_refresh_notifs(post.author_id)
            try:
                _la = post.author
                broadcast_post({
                    "id": post.id, "type": "update",
                    "number": post.number or "",
                    "content": post.content, "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": post.created_at.isoformat() if post.created_at else "",
                    "author": {
                        "id": _la.id, "username": _la.username,
                        "display_name": _la.display_name or _la.username,
                        "avatar": _la.profile_image or "", "header": _la.header_image or "",
                        "summary": _la.summary or "", "is_admin": _la.is_admin,
                        "is_locked": getattr(_la, "is_locked", False),
                        "is_limited": getattr(_la, "is_limited", False),
                        "is_remote": _la.is_remote, "ap_id": _la.remote_url or "",
                    },
                    "likes_count": session.query(Like).filter_by(post_id=post.id).count(),
                    "boosts_count": session.query(Boost).filter_by(post_id=post.id).count(),
                    "replies_count": session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                    "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                    "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data, "my_vote": None, "reactions": {}, "my_reaction": None,
                }, post.author_id, post.visibility or "public", False)
            except Exception:
                pass

        return (200, "Unliked")

    elif obj_type == "Announce":
        actor_url = activity.get("actor", "")
        object_url = obj.get("object", "") if isinstance(obj, dict) else ""
        if isinstance(actor_url, list):
            actor_url = actor_url[0]

        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if post:
                _sign_as = session.query(User).get(post.author_id)
            else:
                _sign_as = None
        actor = _resolve_actor(actor_url, sign_as=_sign_as)
        if not actor:
            return (200, "OK")

        actor_id = actor.id
        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if not post:
                return (200, "OK")
            session.query(Boost).filter_by(user_id=actor_id, post_id=post.id).delete()
            # Delete boost pointer post
            session.query(Post).filter_by(author_id=actor_id, boost_of_id=post.id).delete()
            session.query(Notification).filter_by(
                user_id=post.author_id, from_user_id=actor_id,
                notification_type="boost", post_id=post.id,
            ).delete()
            session.commit()
            from app.timeline_stream import broadcast_refresh_notifs, broadcast_post
            broadcast_refresh_notifs(post.author_id)
            try:
                _ba = post.author
                broadcast_post({
                    "id": post.id, "type": "update",
                    "number": post.number or "",
                    "content": post.content, "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": post.created_at.isoformat() if post.created_at else "",
                    "author": {
                        "id": _ba.id, "username": _ba.username,
                        "display_name": _ba.display_name or _ba.username,
                        "avatar": _ba.profile_image or "", "header": _ba.header_image or "",
                        "summary": _ba.summary or "", "is_admin": _ba.is_admin,
                        "is_locked": getattr(_ba, "is_locked", False),
                        "is_limited": getattr(_ba, "is_limited", False),
                        "is_remote": _ba.is_remote, "ap_id": _ba.remote_url or "",
                    },
                    "likes_count": session.query(Like).filter_by(post_id=post.id).count(),
                    "boosts_count": session.query(Boost).filter_by(post_id=post.id).count(),
                    "replies_count": session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                    "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                    "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data, "my_vote": None, "reactions": {}, "my_reaction": None,
                }, post.author_id, post.visibility or "public", False)
            except Exception:
                pass

        return (200, "Unboosted")

    elif obj_type == "Block":
        actor_url = obj.get("actor", activity.get("actor", ""))
        object_url = obj.get("object", "")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]
        if isinstance(object_url, dict):
            object_url = object_url.get("id", "")

        local_username = _parse_username_from_url(object_url)
        sign_as = None
        if local_username:
            with get_session() as _s:
                _u = _s.query(User).filter_by(username=local_username, is_remote=False).first()
                if _u:
                    sign_as = _u
        remote_user = _resolve_actor(actor_url, sign_as=sign_as)
        if not remote_user:
            return (200, "OK")
        try:
            with get_session() as session:
                remote = session.query(User).filter_by(id=remote_user.id).first()
                if not remote:
                    return (200, "OK")
                local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
                if not local_user:
                    return (200, "OK")
                session.query(UserBlock).filter_by(user_id=remote.id, target_user_id=local_user.id).delete()
                session.commit()
            return (200, "Unblocked")
        except Exception as e:
            logger.error("Error processing Undo Block from %s: %s", actor_url, e)
            return (200, "OK")

    return (200, "OK")


def _handle_update(activity: dict) -> tuple[int, str]:
    object_data = activity.get("object", {})
    if isinstance(object_data, str):
        try:
            import httpx
            resp = httpx.get(object_data, headers={"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}, follow_redirects=True, timeout=10)
            if resp.status_code < 300:
                object_data = resp.json()
            else:
                return (200, "OK")
        except Exception:
            return (200, "OK")
    if isinstance(object_data, dict):
        obj_type = object_data.get("type", "")
        obj_id = object_data.get("id", "")
        if obj_type in ("Person", "Service"):
            _resolve_actor(obj_id, force_refresh=True)
        elif obj_type in ("Note", "Question"):
            with get_session() as session:
                post = session.query(Post).filter_by(ap_id=obj_id).first()
                if post and not post.is_deleted:
                    # Update content/summary
                    new_content = object_data.get("content", "")
                    if new_content:
                        post.content = _normalize_mentions(_sanitize_html(new_content))
                    if "summary" in object_data:
                        post.summary = object_data.get("summary", "")
                    # Update poll data
                    if post.poll_data:
                        one_of = object_data.get("oneOf") or object_data.get("anyOf") or []
                        if isinstance(one_of, list):
                            new_options = []
                            for opt in one_of:
                                if isinstance(opt, dict) and opt.get("name"):
                                    replies = opt.get("replies", {})
                                    votes_count = 0
                                    if isinstance(replies, dict):
                                        votes_count = replies.get("totalItems", 0)
                                    new_options.append({"text": opt["name"], "votes_count": votes_count})
                            if new_options:
                                old_options = post.poll_data.get("options", [])
                                text_to_old = {o.get("text", ""): o for o in old_options}
                                for new_opt in new_options:
                                    old = text_to_old.get(new_opt["text"])
                                    if old:
                                        new_opt["votes_count"] = max(new_opt.get("votes_count", 0), old.get("votes_count", 0))
                                post.poll_data = {**post.poll_data, "options": new_options}
                    # Update emoji tags
                    _process_emoji_tags(object_data.get("tag", []), session)
                    session.commit()
                    try:
                        from app.timeline_stream import broadcast_post
                        _ua = post.author
                        broadcast_post({
                            "id": post.id,
                            "number": post.number or "",
                            "content": post.content,
                            "summary": post.summary or "",
                            "visibility": post.visibility or "public",
                            "created_at": post.created_at.isoformat() if post.created_at else "",
                            "author": {
                                "id": _ua.id, "username": _ua.username,
                                "display_name": _ua.display_name or _ua.username,
                                "avatar": _ua.profile_image or "", "header": _ua.header_image or "",
                                "summary": _ua.summary or "", "is_admin": _ua.is_admin,
                                "is_locked": getattr(_ua, "is_locked", False),
                                "is_limited": getattr(_ua, "is_limited", False),
                                "is_remote": _ua.is_remote, "ap_id": _ua.remote_url or "",
                            },
                    "likes_count": session.query(Like).filter_by(post_id=post.id).count(),
                    "boosts_count": session.query(Boost).filter_by(post_id=post.id).count(),
                    "replies_count": session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                    "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                    "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data, "my_vote": None,
                    "reactions": _build_reactions(session, post.id),
                    "my_reaction": None,
                            "type": "update",
                        }, post.author_id, post.visibility or "public", False)
                    except Exception:
                        pass
    return (200, "Updated")

def _handle_delete(activity: dict) -> tuple[int, str]:
    object_url = activity.get("object", "")
    if isinstance(object_url, dict):
        object_url = object_url.get("id", "")

    if not object_url:
        return (200, "OK")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if post:
            post.is_deleted = True
            session.query(Notification).filter_by(post_id=post.id).delete()
            session.commit()
            try:
                from app.timeline_stream import broadcast_delete
                broadcast_delete(post.id)
            except Exception:
                pass

    return (200, "Deleted")


def _send_delete_post(post: Post, sender: User):
    delete = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{sender.actor_uri()}#delete/{post.id}",
        "type": "Delete",
        "actor": sender.actor_uri(),
        "object": {
            "id": post.ap_id,
            "type": "Note",
        },
    }
    from app.activitypub import broadcast_to_followers
    try:
        broadcast_to_followers(sender, delete)
    except Exception as e:
        logger.warning("Failed to broadcast Delete: %s", e)
    # Also send Delete directly to parent author's inbox for remote replies
    if post.in_reply_to_ap_id:
        try:
            with get_session() as s:
                parent = s.query(Post).filter_by(ap_id=post.in_reply_to_ap_id).first()
                if parent and parent.author and parent.author.is_remote:
                    inbox = parent.author.shared_inbox_url or parent.author.inbox_uri()
                    _post_to_inbox(inbox, delete, sender)
        except Exception as e:
            logger.warning("Failed to send Delete to parent author: %s", e)


def _notify_admins(session, reporter, target_type, target_id, reason):
    import json as _json
    _admins = session.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
    for _a in _admins:
        if _a.id == reporter.id:
            continue
        session.add(Notification(
            user_id=_a.id, from_user_id=reporter.id,
            notification_type="moderation",
            metadata_json=_json.dumps({"type": "report", "target_type": target_type, "target_id": target_id, "target_label": "", "reason": (reason or "")[:200]}),
        ))
    session.flush()
    from app.push import send_push_to_user
    from app.timeline_stream import broadcast_notif_sound
    for _a in _admins:
        if _a.id != reporter.id:
            send_push_to_user(_a.id, "moderation", reporter.username)
            broadcast_notif_sound(_a.id)

def _handle_flag(activity: dict) -> tuple[int, str]:
    logger.info("=== FLAG called ===")
    with get_session() as s:
        actor_url = activity.get("actor")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]
        logger.info("FLAG actor_url=%s", actor_url)
        if not actor_url:
            return (400, "Missing actor")
        reporter = s.query(User).filter_by(remote_url=actor_url).first()
        if not reporter:
            for u in s.query(User).filter(User.is_remote == False).all():
                if u.actor_uri() == actor_url:
                    reporter = u
                    break
        logger.info("FLAG reporter found: %s", reporter is not None)
        if not reporter:
            try:
                reporter = _resolve_actor(actor_url)
                logger.info("FLAG _resolve_actor: %s", reporter is not None)
            except Exception as e:
                logger.warning("FLAG _resolve_actor failed: %s", e)
                reporter = None
        if not reporter:
            try:
                import httpx as _httpx, json as _json
                _r = _httpx.get(actor_url, headers={"Accept": "application/activity+json"}, timeout=10, follow_redirects=True)
                if _r.status_code == 200:
                    _d = _r.json()
                    _pref = _d.get("preferredUsername", "")
                    if _pref:
                        from app.crypto_utils import generate_keypair
                        _domain = urlparse(actor_url).netloc
                        _username = f"{_pref}@{_domain}"
                        _pubkey = _d.get("publicKey", {}).get("publicKeyPem", "") if isinstance(_d.get("publicKey"), dict) else ""
                        _privkey = generate_keypair()[0]
                        _existing = s.query(User).filter_by(remote_url=actor_url).first()
                        if _existing:
                            _existing.public_key = _pubkey or _existing.public_key
                            reporter = _existing
                        else:
                            _by = s.query(User).filter_by(username=_username).first()
                            if _by:
                                _by.remote_url = actor_url
                                _by.public_key = _pubkey or _by.public_key
                                reporter = _by
                            else:
                                reporter = User(
                                    username=_username, remote_url=actor_url,
                                    public_key=_pubkey, private_key=_privkey,
                                    password_hash="", is_remote=True,
                                    inbox_url=_d.get("inbox", ""),
                                    shared_inbox_url=_d.get("endpoints", {}).get("sharedInbox", "") if isinstance(_d.get("endpoints"), dict) else "",
                                    display_name=_d.get("name", _pref), summary=_d.get("summary", ""),
                                    profile_url=_d.get("url", actor_url),
                                )
                                s.add(reporter)
                        s.flush()
                        logger.info("FLAG reporter created via direct fetch: %s", reporter.id)
            except Exception as e:
                logger.warning("FLAG direct fetch failed: %s", e)
        if not reporter:
            return (202, "Accepted (unknown reporter)")
        objects = activity.get("object", [])
        if isinstance(objects, str):
            objects = [objects]
        logger.info("FLAG objects=%s", objects)
        content = activity.get("content", "")
        for obj_url in objects:
            logger.info("FLAG processing obj: %s", obj_url)
            post = s.query(Post).filter_by(ap_id=obj_url).first()
            if post:
                logger.info("FLAG found post id=%s", post.id)
                report = Report(
                    reporter_id=reporter.id, target_type="post", target_id=post.id,
                    reason=content or "Reported via federation", forward_to_remote=False,
                )
                s.add(report)
                _notify_admins(s, reporter, "post", post.id, content)
                continue
            user = s.query(User).filter(User.remote_url == obj_url).first()
            if not user:
                if BASE_URL in obj_url:
                    for _u in s.query(User).filter_by(is_remote=False).all():
                        if _u.actor_uri() == obj_url:
                            user = _u
                            break
            if user and not user.is_remote:
                logger.info("FLAG found local user %s", user.username)
                report = Report(
                    reporter_id=reporter.id, target_type="user", target_id=user.id,
                    reason=content or "Reported via federation", forward_to_remote=False,
                )
                s.add(report)
                _notify_admins(s, reporter, "user", user.id, content)
            else:
                logger.info("FLAG no match for obj: %s", obj_url)
        s.commit()
        from app.timeline_stream import broadcast_refresh_notifs
        broadcast_refresh_notifs()
        logger.info("FLAG done, committed")
    return (200, "Flagged")


def _handle_move(activity: dict) -> tuple[int, str]:
    actor_url = activity.get("actor")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    if not actor_url:
        return (400, "Missing actor")

    old_actor_url = activity.get("object", "")
    if isinstance(old_actor_url, dict):
        old_actor_url = old_actor_url.get("id", "")
    if isinstance(old_actor_url, list):
        old_actor_url = old_actor_url[0] if old_actor_url else ""
    if not old_actor_url:
        return (400, "Missing object")

    new_actor_url = activity.get("target", "")
    if isinstance(new_actor_url, dict):
        new_actor_url = new_actor_url.get("id", "")
    if isinstance(new_actor_url, list):
        new_actor_url = new_actor_url[0] if new_actor_url else ""
    if not new_actor_url:
        return (400, "Missing target")

    from app.config import BASE_URL
    with get_session() as session:
        local_user = None
        for u in session.query(User).filter(User.is_remote == False).all():
            if u.actor_uri() == old_actor_url:
                local_user = u
                break
        if not local_user:
            local_user = session.query(User).filter(
                User.remote_url == old_actor_url,
                User.is_remote == True,
            ).first()
        if not local_user:
            return (200, "OK (not a local/known account)")

        new_actor = _resolve_actor(new_actor_url)
        if not new_actor:
            return (404, "New actor not found")

        # Verify that the new account has the old account in its aliases
        new_actor_local = session.query(User).filter_by(id=new_actor_id, is_remote=False).first()
        if new_actor_local:
            aliases = new_actor_local.aliases or []
            if old_actor_url not in aliases and local_user.actor_uri() not in aliases:
                return (403, "New account has not aliased the old account")
        elif new_actor.is_remote:
            aliases = new_actor.aliases or []
            if old_actor_url not in aliases and local_user.remote_url not in aliases:
                return (403, "New account has not aliased the old account")

        followers = session.query(Follow).filter_by(following_id=local_user.id, accepted=True).all()
        moved_count = 0
        for f in followers:
            existing = session.query(Follow).filter_by(
                follower_id=f.follower_id, following_id=new_actor_id
            ).first()
            if not existing:
                f.following_id = new_actor_id
                moved_count += 1
        session.commit()

    logger.info("Move: moved %d followers from %s to %s", moved_count, old_actor_url, new_actor_url)
    return (200, f"Moved {moved_count} followers")


def _send_flag(reporter: User, target_type: str, target_obj, reason: str, rule_ids: list = None):
    if target_type == "post":
        object_id = target_obj.ap_id
        target_actor_uri = target_obj.author.actor_uri()
    elif target_type in ("novel", "episode"):
        return
    else:
        return
    content = reason
    if rule_ids:
        rules_text = ", ".join(str(rid) for rid in rule_ids)
        content = f"[Rules violated: {rules_text}] {reason}"
    flag = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{reporter.actor_uri()}/flags/{target_obj.id}",
        "type": "Flag",
        "actor": reporter.actor_uri(),
        "object": [target_actor_uri, object_id],
        "content": content,
    }
    author = target_obj.author
    inbox = author.inbox_url or (author.actor_uri().rstrip("/") + "/inbox")
    if inbox:
        _post_to_inbox(inbox, flag, reporter)
    else:
        logger.warning("_send_flag: no inbox for %s", author.actor_uri())
        raise ValueError(f"No inbox for {author.actor_uri()}")


def _deliver_sync(inbox_url: str, body: bytes, headers: dict) -> bool:
    for attempt in range(3):
        try:
            resp = httpx.post(inbox_url, content=body, headers=headers, timeout=15)
            if resp.is_success:
                return True
            if resp.status_code in (400, 401, 403, 404, 405, 410, 422):
                return False
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
    return False


def _post_to_inbox(inbox_url: str, activity: dict, sender: User):
    if not _validate_url(inbox_url):
        return
    body = json.dumps(activity, ensure_ascii=False).encode("utf-8")
    import base64 as _b64
    digest = _b64.b64encode(hashlib.sha256(body).digest()).decode()
    date = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )

    parsed = urlparse(inbox_url)
    path = parsed.path or "/"
    created = int(time.time())
    signed_string = f"(request-target): post {path}\nhost: {parsed.netloc}\ndate: {date}\ndigest: SHA-256={digest}\n(created): {created}"

    signature = sign_string(signed_string, get_private_key(sender, SECRET_KEY))
    signature_header = (
        f'keyId="{sender.actor_uri()}#main-key",'
        f'algorithm="hs2019",'
        f'created="{created}",'
        f'headers="(request-target) host date digest (created)",'
        f'signature="{signature}"'
    )

    headers = {
        "Content-Type": "application/activity+json",
        "Signature": signature_header,
        "Date": date,
        "Digest": f"SHA-256={digest}",
        "Host": parsed.netloc,
    }

    # Immediate delivery attempt with inline retry
    if _deliver_sync(inbox_url, body, headers):
        return

    # Queue for background retry if immediate delivery fails
    from app.models import PendingDelivery
    with get_session() as session:
        session.add(PendingDelivery(
            inbox_url=inbox_url,
            activity_json=json.dumps(activity, ensure_ascii=False),
            sender_id=sender.id,
            status="pending",
        ))
        session.commit()


def send_to_shared_inbox(user: User, activity: dict):
    with get_session() as session:
        followers = session.query(Follow).filter(
            Follow.follower_id == user.id,
            Follow.following.has(is_remote=True),
        ).all()

    sent = set()
    for f in followers:
        target = f.following
        inbox = target.shared_inbox_url or target.inbox_uri()
        if inbox in sent:
            continue
        sent.add(inbox)
        _post_to_inbox(inbox, activity, user)


def _process_emoji_tags(tags: list, session):
    """Parse Emoji tags from an ActivityPub object, download and save custom emojis."""
    if not tags or not isinstance(tags, list):
        return
    from app.utils.storage import get_storage
    _storage = get_storage()
    EMOJI_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "public", "emojis")
    os.makedirs(EMOJI_DIR, exist_ok=True)
    for tag in tags:
        if not isinstance(tag, dict) or tag.get("type") != "Emoji":
            continue
        name = tag.get("name", "")
        if not name.startswith(":") or not name.endswith(":"):
            continue
        keyword = name[1:-1].strip().lower().replace(" ", "_")
        if not keyword or not re.match(r'^[a-z0-9_]+$', keyword):
            continue
        icon = tag.get("icon", {})
        # icon can be a single object or a list per ActivityStreams spec
        if isinstance(icon, list):
            icon = icon[0] if icon else {}
        img_url = ""
        if isinstance(icon, dict):
            img_url = icon.get("url", "") or icon.get("href", "")
        elif isinstance(icon, str):
            img_url = icon
        if not img_url:
            continue
        if not img_url.startswith("http"):
            continue

        # Extract domain from the emoji ActivityPub ID
        emoji_id = tag.get("id", "")
        from urllib.parse import urlparse
        domain = urlparse(emoji_id).netloc if emoji_id else ""

        existing = session.query(CustomEmoji).filter_by(keyword=keyword, domain=domain).first()
        if existing:
            continue

        if not _validate_url(img_url):
            continue
        from PIL import Image
        import httpx
        try:
            resp = httpx.get(img_url, follow_redirects=True, timeout=15)
            if resp.status_code != 200:
                continue
            ext = "png"
            ct = resp.headers.get("content-type", "")
            if "jpeg" in ct or "jpg" in ct:
                ext = "jpg"
            elif "webp" in ct:
                ext = "webp"
            elif "gif" in ct:
                ext = "gif"
            elif "png" in ct:
                ext = "png"
            else:
                ext = resp.url.path.rsplit(".", 1)[-1].lower() if "." in resp.url.path else "png"
                if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
                    ext = "png"
            if ext == "jpeg":
                ext = "jpg"
            file_name = f"{uuid.uuid4().hex}.{ext}"
            remote_dir = os.path.join(EMOJI_DIR, "remote")
            os.makedirs(remote_dir, exist_ok=True)
            file_path = os.path.join(remote_dir, file_name)

            # Check aspect ratio — skip if too wide (>2x height)
            tmp = Image.open(io.BytesIO(resp.content))
            w, h = tmp.size
            tmp.close()
            if h > 0 and w / h > 2.0:
                continue

            if ext == "gif":
                data = resp.content
            else:
                file_name = f"{uuid.uuid4().hex}.webp"
                file_path = os.path.join(remote_dir, file_name)
                img = Image.open(io.BytesIO(resp.content))
                if img.mode == "RGBA" or img.mode == "P":
                    img = img.convert("RGBA")
                else:
                    img = img.convert("RGB")
                if img.width > 66 or img.height > 66:
                    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="WEBP", quality=100)
                data = buf.getvalue()
            # Save via storage backend (S3 or local)
            try:
                _storage.save(f"emojis/remote/{file_name}", data, f"image/{ext}")
            except Exception:
                os.makedirs(remote_dir, exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(data)
            emoji = CustomEmoji(
                keyword=keyword,
                file_name=file_name,
                category="remote",
                aliases=[],
                source_url=img_url,
                domain=domain,
            )
            session.add(emoji)
        except Exception as e:
            logger.warning("Failed to process remote emoji %s: %s", keyword, e)


def broadcast_to_followers(user: User, activity: dict):
    with get_session() as session:
        followers = session.query(Follow).filter(
            Follow.following_id == user.id,
            Follow.follower.has(is_remote=True),
        ).all()

    sent = set()
    for f in followers:
        follower = f.follower
        inbox = follower.shared_inbox_url or follower.inbox_uri()
        if inbox in sent:
            continue
        domain = urlparse(inbox).hostname or ""
        if not _federation_allowed(domain):
            continue
        sent.add(inbox)
        _post_to_inbox(inbox, activity, user)
