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

from app.models import User, Post, Follow, Like, Boost, Vote, Notification, Report, RemoteMedia, CustomEmoji, FederationBlock, AllowedServer, MutedServer, ServerSetting, UserBlock, Tag, get_session
from app.config import BASE_URL, SECRET_KEY
from app.crypto_utils import generate_keypair, sign_string, encrypt_key, get_private_key

WRIT_USER_AGENT = "WRIT/1.0 (+https://daydream.ink)"


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


import re
from urllib.parse import urlparse

def _normalize_mentions(html: str) -> str:
    """
    Convert Mastodon-style mention HTML to plain text.
    If the text lacks a domain (e.g. just '@user'), parses the href attribute 
    to append the correct '@domain' and prevent local user collision.
    """
    def _strip_mention(m):
        full_tag_text = m.group(0)
        # 1. <a> 태그의 href 주소 추출
        href_match = re.search(r'href=["\']([^"\']+)["\']', full_tag_text, re.IGNORECASE)
        domain = None
        if href_match:
            try:
                # URL에서 도메인(예: remote.com)만 쏙 빼오기
                parsed_url = urlparse(href_match.group(1))
                domain = parsed_url.netloc.lower()
            except Exception:
                pass
        # 2. 모든 HTML 태그를 지우고 알맹이 텍스트만 추출
        text = re.sub(r'<[^>]+>', '', full_tag_text).strip()
        # 3. 텍스트 내부에서 @아이디 파싱
        match = re.search(r'@([\w.-]+)(?:@([\w.-]+))?', text)
        if not match:
            return text
        username = match.group(1)
        text_domain = match.group(2)
        # 4. 텍스트에 이미 도메인이 있다면 그걸 그대로 사용
        if text_domain:
            return f"@{username}@{text_domain}"
        # 5. 텍스트엔 도메인이 없는데 <a> 링크 도메인이 존재한다면?
        # (단, 우리 서비스 내부 링크일 수도 있으니 로컬 도메인은 붙이지 않도록 방어 코드 추가 가능)
        if domain:
            # 예: @jack -> @jack@remote.com 으로 복원
            return f"@{username}@{domain}"
        return f"@{username}"
    # 1. <span> wrapper가 있는 형태 처리 (클래스 순서 무관)
    html = re.sub(
        r'<span[^>]*class="[^"]*\bh-card\b[^"]*"[^>]*>\s*<a[^>]*class="(?=[^"]*\bu-url\b)(?=[^"]*\bmention\b)[^"]*"[^>]*>.*?</a>\s*</span>',
        _strip_mention, html, flags=re.IGNORECASE | re.DOTALL
    )
    # 2. <a> 태그 단독 형태 처리 (클래스 순서 무관)
    html = re.sub(
        r'<a[^>]*class="(?=[^"]*\bu-url\b)(?=[^"]*\bmention\b)[^"]*"[^>]*>.*?</a>',
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

def _validated_get(url: str, headers: dict = None, timeout: int = 15, max_redirects: int = 5):
    """HTTP GET with SSRF-safe redirect validation."""
    if not _validate_url(url):
        return None
    client = httpx.Client(follow_redirects=False, timeout=timeout)
    try:
        resp = client.get(url, headers=headers or {})
        for _ in range(max_redirects):
            if resp.status_code not in (301, 302, 307, 308):
                return resp
            location = resp.headers.get("location", "")
            if not location:
                return resp
            from urllib.parse import urljoin as _urljoin
            url = _urljoin(url, location)
            if not _validate_url(url):
                logger.warning("SSRF blocked redirect to %s", url)
                return None
            resp = client.get(url, headers=headers or {})
        return resp
    except Exception:
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
        r = _validated_get(image_url, headers={"User-Agent": WRIT_USER_AGENT}, timeout=15)
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
        headers = {"Accept": "application/activity+json, application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\"", "User-Agent": WRIT_USER_AGENT}
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
        resp = _validated_get(collection_url, headers=headers, timeout=10)
        if resp is not None and resp.status_code == 200:
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

    data = None
    if sign_as:
        try:
            import datetime, time
            from app.crypto_utils import sign_string, get_private_key
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

    # Download images BEFORE opening DB session to avoid holding connections during network I/O
    base_username_clean = local_username.replace("@", "_")
    _dl_avatar = _save_remote_avatar(avatar_url, base_username_clean) if avatar_url else ""
    _dl_header = _save_remote_image(header_url, "headers", base_username_clean) if header_url else ""
    _dl_followers = _fetch_remote_count(data.get("followers", ""), sign_as)
    _dl_following = _fetch_remote_count(data.get("following", ""), sign_as)

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
            resp = httpx.get(obj, headers={"Accept": "application/activity+json, application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\"", "User-Agent": WRIT_USER_AGENT}, timeout=10)
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

    # Resolve actor BEFORE opening session (network I/O + its own session)
    remote_accepter = _resolve_actor(accepter_url)
    if not remote_accepter:
        return (200, "OK")
    remote_accepter_id = remote_accepter.id

    with get_session() as session:
        local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
        if not local_user:
            return (200, "OK")

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

    # Convert web URL /@username/id to AP URL /users/username/statuses/id
    m = re.match(r'^(https?://[^/]+)/@(\w+(?:@\S+)?)/([a-f0-9]+)(\?.*)?$', url)
    if m:
        base, username, status_id, query = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        url = f"{base}/users/{username}/statuses/{status_id}{query}"

    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(url)
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
        resp = _validated_get(url, headers=headers, timeout=15)
        if resp is not None and resp.status_code == 200:
            data = resp.json()
    except Exception as e:
        print(f"[FETCH-POST] url={url} error={e}", flush=True)

    if data is None and signer:
        try:
            resp = _validated_get(url, headers={"Accept": "application/activity+json"}, timeout=15)
            if resp is not None and resp.status_code == 200:
                data = resp.json()
        except Exception as e:
            print(f"[FETCH-POST] retry url={url} error={e}", flush=True)

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

    # ------------------ [여기서부터 수정] ------------------
    # 1. obj['tag'] 내부에 Mention 타입이 명시되어 있는지 확인
    tags = obj.get("tag", [])
    if isinstance(tags, dict): 
        tags = [tags]
    elif not isinstance(tags, list): 
        tags = []

    has_mention_tag = False
    mentioned_ids = []
    for t in tags:
        if not isinstance(t, dict):
            continue
        # 조건 A: 표준 'Mention' 타입 객체인 경우
        is_mention_type = t.get("type") == "Mention"
        # 조건 B: name 필드에 '@이름@도메인' 포맷이 들어온 경우 (예: @siarte@serafuku.moe)
        name_val = t.get("name", "") or ""
        # 골뱅이가 2개 이상 들어있고 @로 시작하는지 체크
        is_double_at = name_val.startswith("@") and name_val.count("@") >= 2
        if is_mention_type or is_double_at:
            has_mention_tag = True
            actor_href = t.get("href", "")
            if not actor_href:
                continue
            try:
                # [핵심] 멘션된 원격 유저의 정보를 내 DB에 확실하게 동기화/생성합니다.
                _resolve_actor(actor_href)
                # 생성/조회된 유저를 DB에서 긁어와 ID를 추가합니다.
                mentioned_user = session.query(User).filter_by(remote_url=actor_href).first()
                if mentioned_user:
                    mentioned_ids.append(mentioned_user.id)
            except Exception as e:
                # 멘션 유저 한 명 해결하다가 전체 글 수집이 터지지 않도록 예외 처리
                print(f"[FETCH-POST] Failed to resolve mentioned actor={actor_href}: {e}", flush=True)
    mentioned_ids = list(set(mentioned_ids))

    # 2. 공개 범위(Visibility) 판별 조건문
    # 전체 공개(Public) 주소가 수신처에 없고, 멘션 태그가 감지되면 "mention"으로 지정합니다.
    if pub not in all_auds and has_mention_tag:
        vis = "mention"
    elif pub in to:
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

    # NOTE: parent fetch uses session (may do network I/O via recursive _fetch_remote_post)
    in_reply_to_id = None
    if in_reply_to_ap:
        parent = session.query(Post).filter_by(ap_id=in_reply_to_ap).first()
        if parent:
            in_reply_to_id = parent.id
        else:
            parent = _fetch_remote_post(in_reply_to_ap, signer, session, _depth + 1)
            if parent:
                in_reply_to_id = parent.id

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
                                    "is_locked": getattr(_ra, "is_locked", false),
                                    "is_limited": getattr(_ra, "is_limited", false),
                                    "is_remote": _ra.is_remote, "ap_id": _ra.remote_url or "",
                                },
                                "likes_count": 0, "boosts_count": 0, "replies_count": 0,
                                "liked": false, "boosted": false, "bookmarked": false, "is_mine": false,
                                "is_dm": false, "is_sensitive": getattr(reply_to_post, "is_sensitive", false) or false,
                                "ap_id": reply_to_post.ap_id or "", "media_attachments": reply_to_post.media_attachments or [],
                                "poll_data": reply_to_post.poll_data, "my_vote": none, "reactions": {}, "my_reaction": none,
                            }, reply_to_post.author_id, reply_to_post.visibility or "public", false)
                        except exception:
                            pass
            # mastodon poll votes: create(note) with name + inreplyto + no content
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
                                return (200, "poll ended")
                        except (valueerror, typeerror) as ex:
                            pass
                    existing_vote = session.query(vote).filter_by(user_id=actor_id, post_id=poll_post.id).first()
                    if existing_vote:
                        if existing_vote.option_index == option_idx:
                            return (200, "already voted")
                        options[existing_vote.option_index]["votes_count"] = max(0, options[existing_vote.option_index].get("votes_count", 0) - 1)
                        existing_vote.option_index = option_idx
                    else:
                        session.add(vote(user_id=actor_id, post_id=poll_post.id, option_index=option_idx))
                    import copy
                    new_options = copy.deepcopy(options)
                    new_options[option_idx]["votes_count"] = new_options[option_idx].get("votes_count", 0) + 1
                    poll_post.poll_data = {**poll_post.poll_data, "options": new_options}
                    session.commit()
                    from app.timeline_stream import broadcast_post, broadcast_refresh_notifs
                    # notify poll author + all voters
                    _voter_ids = {v.user_id for v in session.query(vote).filter_by(post_id=poll_post.id).all()}
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
                    }, poll_post.author_id, poll_post.visibility or "public", false)
                    return (200, "voted")

            # Parse mentions ONLY from AP tag array (No regex body parsing)
            mentioned_hrefs = set()
            mentioned_names = set()
            # Get actor domain for same-server mention resolution
            _actor_domain = urlparse(actor.remote_url).hostname if actor.remote_url else ""
            # Extract from AP tag array
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
            print(f"[_handle_create MENTION DEBUG] actor={actor_url} to={to} cc={cc}", flush=True)
            print(f"[_handle_create MENTION DEBUG] mentioned_hrefs={mentioned_hrefs} mentioned_names={mentioned_names}", flush=True)

            mentioned_ids = []
            _seen_ids = set()
            # Process href-based mentions FIRST (most reliable: from AP Mention tag href or to/cc)
            if mentioned_hrefs:
                for _href in mentioned_hrefs:
                    _matched = False
                    # 1. 로컬 유저 매칭 우선 (same-domain shadow user 문제 방지)
                    if BASE_URL in _href:
                        for _u in session.query(User).filter_by(is_remote=False).all():
                            local_uris = {
                                _u.actor_uri().rstrip("/"),
                                _u.actor_uri().replace("/users/", "/@").rstrip("/")
                            }
                            if _href in local_uris and _u.id not in _seen_ids:
                                mentioned_ids.append(_u.id)
                                _seen_ids.add(_u.id)
                                print(f"[_handle_create MENTION] LOCAL MATCH: href={_href} -> uid={_u.id} username={_u.username}", flush=True)
                                _matched = True
                                break
                    # 2. 원격 유저 매칭 (로컬에서 매칭 안 됐을 때만)
                    if not _matched:
                        u = session.query(User).filter(User.remote_url == _href).first()
                        if u and u.id not in _seen_ids:
                            mentioned_ids.append(u.id)
                            _seen_ids.add(u.id)
                            print(f"[_handle_create MENTION] REMOTE MATCH: href={_href} -> uid={u.id} username={u.username}", flush=True)
                        elif not u:
                            print(f"[_handle_create MENTION] NO MATCH: href={_href}", flush=True)
            if mentioned_names:
                for _name in mentioned_names:
                    if '@' in _name:
                        _lp, _dom = _name.split('@', 1)
                        from urllib.parse import urlparse as _urlparse
                        u = session.query(User).filter(
                            User.username == _lp, User.is_remote == True,
                        ).first()
                        if u and u.id not in _seen_ids and u.remote_url:
                            _p = _urlparse(u.remote_url)
                            if _p.hostname and _p.hostname.lower() == _dom.lower():
                                mentioned_ids.append(u.id)
                                _seen_ids.add(u.id)
                                continue
                        # username may contain @domain, try like + domain check
                        candidates = session.query(User).filter(
                            User.username.like(f"{_lp}@%"),
                            User.is_remote == True,
                        ).all()
                        for _c in candidates:
                            if _c.id in _seen_ids:
                                continue
                            if _c.remote_url:
                                _p = _urlparse(_c.remote_url)
                                if _p.hostname and _p.hostname.lower() == _dom.lower():
                                    mentioned_ids.append(_c.id)
                                    _seen_ids.add(_c.id)
                                    break
                    else:
                        # same-domain remote user only (local user handled via href already)
                        if _actor_domain:
                            u = session.query(User).filter(
                                User.username == _name, User.is_remote == True,
                                User.remote_url.contains(_actor_domain)
                            ).first()
                            if u and u.id not in _seen_ids:
                                mentioned_ids.append(u.id)
                                _seen_ids.add(u.id)

            print(f"[_handle_create MENTION RESULT] mentioned_ids={mentioned_ids} (from hrefs={mentioned_hrefs}, names={mentioned_names})", flush=True)
            actor_domain = urlparse(actor.remote_url).hostname if actor.remote_url else ""
            if actor_domain:
                mute_entry = session.query(MutedServer).filter_by(domain=actor_domain).first()
                if mute_entry and mute_entry.muted and visibility == "public":
                    visibility = "home"

            # Process custom emoji tags and media BEFORE session (network I/O)
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

            # Parse #hashtags from content and sync with Tag model (so hashtag search includes remote posts)
            for _t in re.findall(r'(?<!\w)#([\w_가-힣]+)', content or ""):
                _existing = session.query(Tag).filter_by(name=_t.lower()).first()
                if not _existing:
                    _existing = Tag(name=_t.lower())
                    session.add(_existing)
                    session.flush()
                post.tag_list.append(_existing)

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
            # Process emoji tags AFTER commit (separate session for HTTP I/O)
            try:
                with get_session() as emoji_s:
                    _process_emoji_tags(obj.get("tag", []), emoji_s)
                    emoji_s.commit()
            except Exception:
                pass
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
                from app.models import CustomEmoji as _CustomEmoji
                author = post.author
                _ap_emoji_kws = set()
                for _tag in (obj.get("tag", []) or []):
                    if not isinstance(_tag, dict) or _tag.get("type") != "Emoji":
                        continue
                    _name = _tag.get("name", "")
                    if _name.startswith(":") and _name.endswith(":"):
                        _ap_emoji_kws.add(_name[1:-1].strip().lower().replace(" ", "_"))
                _broadcast_emojis = []
                if _ap_emoji_kws:
                    for e in session.query(_CustomEmoji).filter(_CustomEmoji.keyword.in_(_ap_emoji_kws)).all():
                        _sub = "remote" if e.domain or e.category == "remote" else "local"
                        _broadcast_emojis.append({"keyword": e.keyword, "file_name": e.file_name, "url": f"/emojis/{_sub}/{e.file_name}", "aliases": e.aliases or []})
                _reply_ctx = None
                if reply_to_post and not getattr(reply_to_post, 'is_deleted', False):
                    _rp_author = reply_to_post.author
                    _reply_ctx = {
                        "id": reply_to_post.id,
                        "number": reply_to_post.number or "",
                        "content": (reply_to_post.content or "")[:200],
                        "author": {
                            "id": _rp_author.id, "username": _rp_author.username,
                            "display_name": _rp_author.display_name or _rp_author.username,
                            "avatar": _rp_author.profile_image or "",
                            "header": _rp_author.header_image or "",
                            "summary": _rp_author.summary or "", "is_admin": _rp_author.is_admin,
                            "is_locked": getattr(_rp_author, "is_locked", False),
                            "is_limited": getattr(_rp_author, "is_limited", False),
                            "is_remote": _rp_author.is_remote, "ap_id": _rp_author.remote_url or "",
                        },
                        "visibility": reply_to_post.visibility or "public",
                    }
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
                    "mentioned_user_ids": mentioned_ids,
                    "reply_context": _reply_ctx,
                    "_emojis": _broadcast_emojis,
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
    reaction = activity.get("_misskey_reaction", activity.get("content", activity.get("reaction", "")))

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
        if reaction and reaction.startswith(":") and reaction.endswith(":"):
            _kw = reaction[1:-1]
            _existing_emoji = session.query(CustomEmoji).filter_by(keyword=_kw).first()
            if not _existing_emoji:
                # Do emoji HTTP download outside this session to avoid holding connection
                _emoji_data = None
                tags = activity.get("tag", []) or []
                for _tag in tags:
                    if isinstance(_tag, dict) and _tag.get("type") == "Emoji":
                        _icon = _tag.get("icon", {})
                        _url = _icon.get("url", "") if isinstance(_icon, dict) else ""
                        _tag_id = _tag.get("id", "")
                        _domain = urlparse(_tag_id).netloc if _tag_id else ""
                        if _url:
                            try:
                                import httpx as _httpx
                                _resp = _httpx.get(_url, headers={"User-Agent": WRIT_USER_AGENT}, timeout=10)
                                if _resp.status_code == 200:
                                    _ext = _url.rsplit(".", 1)[-1].split("?")[0] if "." in _url else "png"
                                    _fname = f"{_kw}.{_ext}"
                                    _emoji_data = (_fname, _resp.content, f"image/{_ext}", _domain)
                            except Exception as e:
                                logger.warning("Failed to download remote emoji %s: %s", _kw, e)
                        break
                if _emoji_data:
                    _fname, _content, _mime, _domain = _emoji_data
                    from app.utils.storage import get_storage
                    _storage = get_storage()
                    try:
                        _storage.save(f"emojis/remote/{_fname}", _content, _mime)
                        with get_session() as emoji_s:
                            emoji_s.add(CustomEmoji(keyword=_kw, file_name=_fname, category="remote", domain=_domain))
                            emoji_s.commit()
                        logger.info("Imported remote emoji: %s from %s", _kw, _domain)
                    except Exception as e:
                        logger.warning("Failed to save remote emoji %s: %s", _kw, e)

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
    raw_object = activity.get("object")
    object_url = raw_object if isinstance(raw_object, str) else ""
    activity_id = activity.get("id", "")
    print(f"[ANNOUNCE] actor={actor_url} object_type={type(raw_object).__name__} object_url={object_url[:120]}", flush=True)

    if not object_url and isinstance(raw_object, dict):
        object_url = raw_object.get("id", "")
        print(f"[ANNOUNCE] embedded object, extracted id={object_url[:120]}", flush=True)

    if not object_url:
        print("[ANNOUNCE] no object_url, returning early", flush=True)
        return (200, "OK")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        _sign_as = session.query(User).get(post.author_id) if post else None
    print(f"[ANNOUNCE] db_post={'found id='+str(post.id) if post else 'none'}", flush=True)
    actor = _resolve_actor(actor_url, sign_as=_sign_as)
    if not actor:
        print("[ANNOUNCE] actor not found, returning 404", flush=True)
        return (404, "Actor not found")

    actor_id = actor.id
    actor_username = actor.username

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        print(f"[ANNOUNCE] session2 post={'found id='+str(post.id) if post else 'none'}", flush=True)
        if not post:
            _local_signer = session.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == actor_id, User.is_remote == False).first()
            if not _local_signer:
                _local_signer = session.query(User).filter_by(is_remote=False).first()
            try:
                post = _fetch_remote_post(object_url, _local_signer, session)
                print(f"[ANNOUNCE] fetch_remote_post result={'id='+str(post.id) if post else 'None'}", flush=True)
            except Exception as e:
                logger.warning("Announce: _fetch_remote_post failed for %s: %s", object_url, e)
                print(f"[ANNOUNCE] fetch_remote_post EXCEPTION: {e}", flush=True)
                post = None
            if not post:
                logger.warning("Announce: could not fetch remote post %s", object_url)
                print(f"[ANNOUNCE] could not fetch remote post, returning early", flush=True)
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

        # 1. 안전하게 DB 세션이 활성화되어 있을 때 미리 _actor와 post.author(_a)를 가져옵니다.
        _actor = session.query(User).get(actor_id)
        _a = post.author

        # 2. 통계 개수 조회도 커밋 전에 안전하게 미리 해둡니다.
        likes_cnt = session.query(Like).filter_by(post_id=post.id).count()
        boosts_cnt = session.query(Boost).filter_by(post_id=post.id).count()
        replies_cnt = session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count()
        reactions_data = _build_reactions(session, post.id)

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

        # 5. 커밋 이후 외부 연동 (푸시 및 스트리밍) 처리
        if not existing_n:
            from app.push import send_push_to_user
            from app.timeline_stream import broadcast_notif_sound
            send_push_to_user(post.author_id, "boost", actor_username, post.id)
            broadcast_notif_sound(post.author_id)

        try:
            from app.timeline_stream import broadcast_post
            def _safe_user_json(u):
                if not u:
                    return None
                role = getattr(u, 'role', 'user') or 'user'
                return {
                    "id": u.id, "username": u.username,
                    "display_name": u.display_name or u.username,
                    "avatar": u.profile_image or "", "header": u.header_image or "",
                    "summary": u.summary or "", "is_admin": u.is_admin,
                    "is_locked": getattr(u, "is_locked", False) or False,
                    "is_limited": getattr(u, "is_limited", False) or False,
                    "is_frozen": getattr(u, "is_frozen", False) or False,
                    "is_deceased": getattr(u, "is_deceased", False) or False,
                    "is_deactivated": getattr(u, "is_deactivated", False) or False,
                    "is_sensitive": getattr(u, "is_sensitive", False) or False,
                    "is_remote": u.is_remote, "role": role,
                    "show_badge": getattr(u, "show_badge", False) or False,
                    "email_verified": getattr(u, "email_verified", False) or False,
                    "default_visibility": getattr(u, "default_visibility", "public") or "public",
                    "display_handle": getattr(u, "display_handle", "") or "",
                    "is_bot": getattr(u, "is_bot", False) or False,
                    "pinned_posts": (u.pinned_posts or []) if hasattr(u, 'pinned_posts') else [],
                    "pinned_series": (u.pinned_series or []) if hasattr(u, 'pinned_series') else [],
                    "episode_default_visibility": getattr(u, "episode_default_visibility", "public") or "public",
                    "follow_list_visibility": getattr(u, "follow_list_visibility", "public") or "public",
                    "custom_fields": (u.custom_fields or []) if hasattr(u, 'custom_fields') else [],
                    "profile_hashtags": (u.profile_hashtags or []) if hasattr(u, 'profile_hashtags') else [],
                    "enable_reactions": getattr(u, "enable_reactions", True),
                    "aliases": (u.aliases or []) if hasattr(u, 'aliases') else [],
                    "moved_to": getattr(u, "moved_to", "") or "",
                }
            _author_data = _safe_user_json(_a)
            if not _author_data:
                _a = session.query(User).get(post.author_id)
                _author_data = _safe_user_json(_a)
            broadcast_post({
                "id": boost_post.id,
                "number": post.number or "",
                "content": post.content,
                "summary": post.summary or "",
                "visibility": post.visibility or "public",
                "created_at": post.created_at.isoformat() if post.created_at else "",
                "author": _author_data,
                "likes_count": likes_cnt,       # 안전하게 받아온 값 대입
                "boosts_count": boosts_cnt,     # 안전하게 받아온 값 대입
                "replies_count": replies_cnt,   # 안전하게 받아온 값 대입
                "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                "poll_data": post.poll_data, "my_vote": None,
                "reactions": reactions_data,
                "my_reaction": None,
                "boosted_by": _safe_user_json(_actor),
                "mentioned_user_ids": [],
            }, actor_id, post.visibility or "public", False)
        except Exception as e:
            logger.warning("Failed to broadcast boost from AP: %s", e)
            print(f"Failed to broadcast boost from AP: {e}", flush=True)

    print(f"[ANNOUNCE] success post_id={post.id} by actor_id={actor_id}", flush=True)
    return (200, "Announced")

def _handle_block(activity: dict) -> tuple[int, str]:
    actor_url = activity.get("actor", "")
    object_url = activity.get("object", "")
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
                return (200, "OK")
            local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
            if not local_user:
                return (200, "OK")
            deleted_incoming = session.query(Follow).filter_by(follower_id=remote.id, following_id=local_user.id).delete()
            deleted_outgoing = session.query(Follow).filter_by(follower_id=local_user.id, following_id=remote.id).delete()
            existing = session.query(UserBlock).filter_by(user_id=remote.id, target_user_id=local_user.id).first()
            if not existing:
                session.add(UserBlock(user_id=remote.id, target_user_id=local_user.id))
                session.commit()
            return (200, "Blocked")
    except Exception as e:
        logger.error("Error processing Block from %s: %s", actor_url, e)
        return (200, "OK")


def _handle_undo(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    obj_type = obj.get("type", "") if isinstance(obj, dict) else ""

    if not isinstance(obj, dict) and isinstance(obj, str):
        fetched = None
        try:
            import httpx
            resp = _validated_get(obj, headers={"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}, timeout=10)
            if resp is not None and resp.status_code < 300:
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
        follower = _resolve_actor(actor_url)
        if not follower:
            return (200, "OK")
        follower_id = follower.id
        with get_session() as session:
            target = session.query(User).filter_by(username=local_username, is_remote=False).first()
            if not target:
                return (200, "OK")
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
            resp = _validated_get(object_data, headers={"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}, timeout=10)
            if resp is not None and resp.status_code < 300:
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
            }, actor_id, post.visibility or "public", False)
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
    actor_url = activity.get("actor")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    logger.info("FLAG actor_url=%s", actor_url)
    if not actor_url:
        return (400, "Missing actor")

    # Try to find or resolve reporter BEFORE opening session (avoids connection hold during network I/O)
    reporter = None
    try:
        with get_session() as _s:
            reporter = _s.query(User).filter_by(remote_url=actor_url).first()
            if not reporter:
                for u in _s.query(User).filter(User.is_remote == False).all():
                    if u.actor_uri() == actor_url:
                        reporter = u
                        break
            if reporter:
                _reporter_id = reporter.id
                _reporter_username = reporter.username
                _reporter_is_remote = reporter.is_remote
    except Exception:
        _reporter_id = None
    logger.info("FLAG reporter found in DB: %s", reporter is not None)

    if not reporter:
        reporter = _resolve_actor(actor_url)
        logger.info("FLAG _resolve_actor: %s", reporter is not None)

    if not reporter:
        try:
            import httpx as _httpx, json as _json
            _r = _validated_get(actor_url, headers={"Accept": "application/activity+json"}, timeout=10)
            if _r.status_code == 200:
                _d = _r.json()
                _pref = _d.get("preferredUsername", "")
                if _pref:
                    from app.crypto_utils import generate_keypair
                    _domain = urlparse(actor_url).netloc
                    _username = f"{_pref}@{_domain}"
                    _pubkey = _d.get("publicKey", {}).get("publicKeyPem", "") if isinstance(_d.get("publicKey"), dict) else ""
                    _privkey = generate_keypair()[0]
                    with get_session() as _s:
                        _existing = _s.query(User).filter_by(remote_url=actor_url).first()
                        if _existing:
                            _existing.public_key = _pubkey or _existing.public_key
                            reporter = _existing
                        else:
                            _by = _s.query(User).filter_by(username=_username).first()
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
                                _s.add(reporter)
                        _s.flush()
                        logger.info("FLAG reporter created via direct fetch: %s", reporter.id)
        except Exception as e:
            logger.warning("FLAG direct fetch failed: %s", e)

    if not reporter:
        return (202, "Accepted (unknown reporter)")

    with get_session() as s:
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

    # Resolve new actor BEFORE session (network I/O)
    new_actor = _resolve_actor(new_actor_url)
    if not new_actor:
        return (404, "New actor not found")
    new_actor_id = new_actor.id

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

        # Verify that the new account has the old account in its aliases
        new_actor_local = session.query(User).filter_by(id=new_actor_id, is_remote=False).first()
        if new_actor_local:
            aliases = new_actor_local.aliases or []
            if old_actor_url not in aliases and local_user.actor_uri() not in aliases:
                return (403, "New account has not aliased the old account")
        else:
            # new_actor is detached; query fresh from session for alias check
            new_actor_in_session = session.query(User).filter_by(id=new_actor_id).first()
            if new_actor_in_session and new_actor_in_session.is_remote:
                aliases = new_actor_in_session.aliases or []
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
            resp = _validated_get(img_url, timeout=15)
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
            # Save to emoji dir (served by /emojis static mount)
            try:
                os.makedirs(remote_dir, exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(data)
            except Exception:
                pass
            # Also save via storage backend for S3
            try:
                _storage.save(f"emojis/remote/{file_name}", data, f"image/{ext}")
            except Exception:
                pass
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
