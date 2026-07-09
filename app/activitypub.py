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

from app.models import User, Post, Follow, Like, Boost, Notification, Report, RemoteMedia, CustomEmoji, FederationBlock, AllowedServer, MutedServer, ServerSetting, get_session
from app.config import BASE_URL, SECRET_KEY
from app.crypto_utils import generate_keypair, sign_string, encrypt_key, get_private_key


logger = logging.getLogger("writ.activitypub")


def _federation_allowed(domain: str) -> bool:
    if not domain:
        return False
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


_SAFE_TAGS = {"p", "br", "a", "strong", "em", "b", "i", "u", "s", "ul", "ol", "li", "blockquote", "code", "pre", "span"}
_SAFE_SCHEMES = {"http", "https", "mailto"}
_SAFE_ATTRS = {"a": {"href", "rel", "class"}, "span": {"class"}, "code": {"class"}, "pre": {"class"}}


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


_PRIVATE_SUBNETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
]


def _validate_url(url: str) -> bool:
    """Reject URLs pointing to private/internal IPs (SSRF protection)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # Block obviously private hostnames without DNS resolution
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    if host.endswith(".local") or host.endswith(".localhost"):
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
    match = re.search(r'/(?:users/)?@?(\w+)$', url)
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
            Post.visibility == "public",
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
        client.close()
        if resp.status_code != 200 or len(resp.content) > max_size:
            return None
        return resp
    except Exception:
        client.close()
        return None

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


def _save_remote_image(image_url: str, prefix: str, local_username: str, old_url: str = "") -> str:
    """Download remote image and save, return URL. If old_url given, delete it first."""
    from app.utils.storage import get_storage
    if not _validate_url(image_url):
        return ""
    ext = image_url.rsplit(".", 1)[-1].lower() if "." in image_url else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    filename = f"{local_username}_{uuid.uuid4().hex[:8]}.{ext}"
    key = f"{prefix}/remote/{filename}"
    try:
        resp = _safe_fetch(image_url)
        if resp:
            storage = get_storage()
            ct = f"image/{ext}"
            new_url = storage.save(key, resp.content, ct)
            if old_url:
                storage.delete(old_url)
            return new_url
    except Exception as e:
        logger.warning("Failed to save remote %s %s: %s", prefix, image_url, e)
    return ""


def _save_remote_avatar(avatar_url: str, local_username: str, old_url: str = "") -> str:
    return _save_remote_image(avatar_url, "avatars", local_username, old_url)


def _resolve_actor(actor_url: str, force_refresh: bool = False) -> Optional[User]:
    with get_session() as session:
        user = session.query(User).filter_by(remote_url=actor_url).first()
        if user and not force_refresh:
            return user

    # Fetch remote actor
    try:
        resp = _safe_fetch(actor_url, timeout=10, headers={"Accept": "application/activity+json"})
        if not resp:
            return None
        data = resp.json()
    except Exception as e:
        logger.warning("Failed to fetch remote actor %s: %s", actor_url, e)
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
            if avatar_url:
                existing.profile_image = _save_remote_avatar(avatar_url, base_username_clean, existing.profile_image)
            if header_url:
                existing.header_image = _save_remote_image(header_url, "headers", base_username_clean, existing.header_image)
            _process_emoji_tags(data.get("tag", []), session)
            session.commit()
            return existing

        # Also check by username in case remote_url is missing/stale
        by_username = session.query(User).filter_by(username=local_username).first()
        if by_username:
            by_username.remote_url = actor_url
            by_username.public_key = public_key_pem or by_username.public_key
            by_username.display_name = data.get("name", by_username.display_name)
            by_username.summary = data.get("summary", by_username.summary)
            if avatar_url:
                by_username.profile_image = _save_remote_avatar(avatar_url, base_username_clean, by_username.profile_image)
            if header_url:
                by_username.header_image = _save_remote_image(header_url, "headers", base_username_clean, by_username.header_image)
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
            remote_url=actor_url,
            shared_inbox_url=data.get("endpoints", {}).get("sharedInbox", ""),
            profile_image=profile_image,
            header_image=header_image,
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

    with get_session() as session:
        target = session.query(User).filter_by(username=local_username, is_remote=False).first()
        if not target:
            return (404, "Target user not found")
        if target.is_locked:
            return (403, "Account is locked")

        follower = _resolve_actor(actor_url)
        if not follower:
            return (404, "Follower not found")

        existing = session.query(Follow).filter_by(
            follower_id=follower.id, following_id=target.id
        ).first()
        if not existing:
            follow = Follow(follower_id=follower.id, following_id=target.id, accepted=True)
            session.add(follow)
            notification = Notification(
                user_id=target.id,
                from_user_id=follower.id,
                notification_type="follow",
            )
            session.add(notification)
            session.commit()

    # Send Accept
    _send_accept(actor_url, activity_id, target)

    return (200, "Followed")


def _send_accept(actor_url: str, activity_id: str, target: User):
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
    _post_to_inbox(actor_url, accept, target)


def _send_reject(actor_url: str, activity_id: str, target: User):
    reject = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{target.actor_uri()}#rejects/{activity_id.split('/')[-1]}",
        "type": "Reject",
        "actor": target.actor_uri(),
        "object": {
            "id": activity_id,
            "type": "Follow",
            "actor": actor_url,
            "object": target.actor_uri(),
        },
    }
    _post_to_inbox(actor_url, reject, target)


def _handle_accept(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    if isinstance(obj, dict):
        follower_url = obj.get("actor", "")
    elif isinstance(obj, str):
        # Object is just a URI — try to fetch the Follow activity
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

    local_username = _parse_username_from_url(accepter_url)
    if not local_username:
        return (200, "OK")

    with get_session() as session:
        local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
        if not local_user:
            return (200, "OK")

        remote_follower = _resolve_actor(follower_url)
        if not remote_follower:
            return (200, "OK")

        follow_rel = session.query(Follow).filter_by(
            following_id=local_user.id,
            follower_id=remote_follower.id,
        ).first()
        if follow_rel:
            follow_rel.accepted = True
            session.commit()

    return (200, "Accepted follow")


def _handle_create(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    if isinstance(obj, dict) and obj.get("type") == "Note":
        raw_actor = activity.get("actor")
        if not raw_actor:
            return (400, "Missing actor")
        actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
        actor = _resolve_actor(actor_url)
        if not actor:
            return (404, "Actor not found")

        post_id = obj.get("id", "")
        content = _sanitize_html(obj.get("content", ""))
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

        if public_uri in to:
            visibility = "public"
        elif public_uri in cc:
            visibility = "home"
        elif any(aud.endswith("/followers") for aud in all_audiences):
            visibility = "followers"
        elif all_audiences and all(aud.startswith("http") for aud in all_audiences if aud):
            visibility = "mention"
        else:
            visibility = "home"

        with get_session() as session:
            existing = session.query(Post).filter_by(ap_id=post_id).first()
            if existing:
                return (200, "Already exists")

            reply_to_post = None
            if in_reply_to:
                reply_to_post = session.query(Post).filter_by(ap_id=in_reply_to).first()

            # Parse mentioned users from content
            mentioned_names = set(re.findall(r'@(\w+)', content or ""))
            mentioned_ids = []
            if mentioned_names:
                mentioned = session.query(User).filter(
                    User.username.in_(mentioned_names)
                ).all()
                mentioned_ids = [u.id for u in mentioned]

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
                author_id=actor.id,
                content=content,
                summary=summary,
                visibility=visibility,
                mentioned_user_ids=mentioned_ids,
                ap_id=post_id,
                in_reply_to_ap_id=in_reply_to,
                in_reply_to_id=reply_to_post.id if reply_to_post else None,
                media_attachments=media_list if media_list else None,
            )
            session.add(post)
            session.flush()

            # Notify local users mentioned or replied to
            if reply_to_post:
                n = Notification(
                    user_id=reply_to_post.author_id,
                    from_user_id=actor.id,
                    notification_type="reply",
                    post_id=post.id,
                )
                session.add(n)

            # Notify local followers
            followers = session.query(Follow).filter(
                Follow.following_id == actor.id,
            ).all()
            for f in followers:
                if not f.follower.is_remote:
                    n = Notification(
                        user_id=f.follower.id,
                        from_user_id=actor.id,
                        notification_type="post",
                        post_id=post.id,
                    )
                    session.add(n)

            session.commit()
            try:
                from app.eventbus import broadcast
                broadcast("new_post", {"post_id": post.id, "author_id": actor.id})
            except Exception as e:
                logger.warning("broadcast failed: %s", e)

        return (200, "Created")
    return (200, "OK")


def _handle_like(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    object_url = activity["object"] if isinstance(activity.get("object"), str) else ""
    activity_id = activity.get("id", "")

    if not object_url:
        return (200, "OK")

    actor = _resolve_actor(actor_url)
    if not actor:
        return (404, "Actor not found")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if not post:
            return (200, "OK")

        existing = session.query(Like).filter_by(user_id=actor.id, post_id=post.id).first()
        if existing:
            return (200, "Already liked")

        like_ap_id = activity_id
        if not like_ap_id:
            like_ap_id = f"{BASE_URL}/likes/{uuid.uuid4()}"

        like = Like(
            user_id=actor.id,
            post_id=post.id,
            ap_id=like_ap_id,
        )
        session.add(like)

        n = Notification(
            user_id=post.author_id,
            from_user_id=actor.id,
            notification_type="like",
            post_id=post.id,
        )
        session.add(n)
        session.commit()

    return (200, "Liked")


def _handle_announce(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    object_url = activity["object"] if isinstance(activity.get("object"), str) else ""
    activity_id = activity.get("id", "")

    if not object_url:
        return (200, "OK")

    actor = _resolve_actor(actor_url)
    if not actor:
        return (404, "Actor not found")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if not post:
            return (200, "OK")

        existing = session.query(Boost).filter_by(user_id=actor.id, post_id=post.id).first()
        if existing:
            return (200, "Already boosted")

        boost_ap_id = activity_id
        if not boost_ap_id:
            boost_ap_id = f"{BASE_URL}/boosts/{uuid.uuid4()}"

        boost = Boost(
            user_id=actor.id,
            post_id=post.id,
            ap_id=boost_ap_id,
        )
        session.add(boost)

        n = Notification(
            user_id=post.author_id,
            from_user_id=actor.id,
            notification_type="boost",
            post_id=post.id,
        )
        session.add(n)
        session.commit()

    return (200, "Announced")


def _handle_undo(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    obj_type = obj.get("type", "") if isinstance(obj, dict) else ""

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
            session.query(Follow).filter_by(
                follower_id=follower.id, following_id=target.id
            ).delete()
            session.commit()

        return (200, "Unfollowed")

    elif obj_type == "Like":
        actor_url = activity.get("actor", "")
        object_url = obj.get("object", "") if isinstance(obj, dict) else ""
        if isinstance(actor_url, list):
            actor_url = actor_url[0]

        actor = _resolve_actor(actor_url)
        if not actor:
            return (200, "OK")

        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if not post:
                return (200, "OK")
            session.query(Like).filter_by(user_id=actor.id, post_id=post.id).delete()
            session.commit()

        return (200, "Unliked")

    elif obj_type == "Announce":
        actor_url = activity.get("actor", "")
        object_url = obj.get("object", "") if isinstance(obj, dict) else ""
        if isinstance(actor_url, list):
            actor_url = actor_url[0]

        actor = _resolve_actor(actor_url)
        if not actor:
            return (200, "OK")

        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if not post:
                return (200, "OK")
            session.query(Boost).filter_by(user_id=actor.id, post_id=post.id).delete()
            session.commit()

        return (200, "Unboosted")

    return (200, "OK")


def _handle_update(activity: dict) -> tuple[int, str]:
    object_data = activity.get("object", {})
    if isinstance(object_data, dict):
        obj_type = object_data.get("type", "")
        obj_id = object_data.get("id", "")
        if obj_type in ("Person", "Service"):
            _resolve_actor(obj_id, force_refresh=True)
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
            session.commit()

    return (200, "Deleted")


def _handle_flag(activity: dict) -> tuple[int, str]:
    with get_session() as s:
        actor_url = activity.get("actor")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]
        if not actor_url:
            return (400, "Missing actor")
        reporter = s.query(User).filter_by(actor_url=actor_url).first()
        if not reporter:
            return (202, "Accepted (unknown reporter)")
        objects = activity.get("object", [])
        if isinstance(objects, str):
            objects = [objects]
        content = activity.get("content", "")
        for obj_url in objects:
            post = s.query(Post).filter_by(ap_id=obj_url).first()
            if post:
                report = Report(
                    reporter_id=reporter.id, target_type="post", target_id=post.id,
                    reason=content or "Reported via federation", forward_to_remote=False,
                )
                s.add(report)
        s.commit()
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

    with get_session() as session:
        local_user = session.query(User).filter(
            User.actor_uri() == old_actor_url,
            User.is_remote == False,
        ).first()
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
        new_actor_local = session.query(User).filter_by(id=new_actor.id, is_remote=False).first()
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
                follower_id=f.follower_id, following_id=new_actor.id
            ).first()
            if not existing:
                f.following_id = new_actor.id
                moved_count += 1
        session.commit()

    logger.info("Move: moved %d followers from %s to %s", moved_count, old_actor_url, new_actor_url)
    return (200, f"Moved {moved_count} followers")


def _send_flag(reporter: User, target_type: str, target_obj, reason: str, rule_ids: list = None):
    if target_type == "post":
        object_id = target_obj.ap_id
        target_actor_uri = target_obj.author.actor_uri()
    elif target_type == "novel":
        return
    elif target_type == "episode":
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
        "object": [object_id],
        "content": content,
    }
    inbox = target_obj.author.inbox_uri()
    if inbox:
        _post_to_inbox(inbox, flag, reporter)


def _deliver_sync(inbox_url: str, body: bytes, headers: dict) -> bool:
    for attempt in range(3):
        try:
            httpx.post(inbox_url, content=body, headers=headers, timeout=15)
            return True
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            logger.warning("Delivery attempt %d/3 failed for %s: %s", attempt + 1, inbox_url, e)
    return False


def _post_to_inbox(inbox_url: str, activity: dict, sender: User):
    if not _validate_url(inbox_url):
        return
    body = json.dumps(activity, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    date = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )

    parsed = urlparse(inbox_url)
    path = parsed.path or "/"
    signed_string = f"(request-target): post {path}\nhost: {parsed.netloc}\ndate: {date}\ndigest: SHA-256={digest}"

    signature = sign_string(signed_string, get_private_key(sender, SECRET_KEY))
    signature_header = (
        f'keyId="{sender.actor_uri()}#main-key",'
        f'algorithm="hs2019",'
        f'created="{int(time.time())}",'
        f'headers="(request-target) host date digest",'
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
        if isinstance(icon, dict):
            img_url = icon.get("url", "")
        elif isinstance(icon, str):
            img_url = icon
        else:
            img_url = ""
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

        EMOJI_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "public", "emojis")
        if not _validate_url(img_url):
            continue
        from PIL import Image
        import httpx
        try:
            resp = httpx.get(img_url, follow_redirects=True, timeout=15)
            if resp.status_code != 200:
                continue
            ext = "png"
                # Try to guess ext from content type
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
            file_path = os.path.join(EMOJI_DIR, file_name)

            # Check aspect ratio — skip if too wide (>2x height)
            tmp = Image.open(io.BytesIO(resp.content))
            w, h = tmp.size
            tmp.close()
            if h > 0 and w / h > 2.0:
                continue

            if ext == "gif":
                with open(file_path, "wb") as f:
                    f.write(resp.content)
            else:
                file_name = f"{uuid.uuid4().hex}.webp"
                file_path = os.path.join(EMOJI_DIR, file_name)
                img = Image.open(io.BytesIO(resp.content))
                if img.mode == "RGBA" or img.mode == "P":
                    img = img.convert("RGBA")
                else:
                    img = img.convert("RGB")
                # Halve dimensions if original is > 66px (so halved size >= 33)
                if img.width > 66 or img.height > 66:
                    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
                img.save(file_path, format="WEBP", quality=100)
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
            logger.info("Skipping broadcast to blocked domain: %s", domain)
            continue
        sent.add(inbox)
        _post_to_inbox(inbox, activity, user)
