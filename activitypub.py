import datetime
import io
import ipaddress
import json
import hashlib
import logging
import os
import re
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

from models import User, Post, Follow, Like, Boost, Notification, CustomEmoji, get_session
from sqlalchemy.exc import IntegrityError
from config import BASE_URL, PUBLIC_URI, SECRET_KEY
from crypto_utils import generate_keypair, sign_string, verify_signature, encrypt_key, decrypt_key, get_private_key


logger = logging.getLogger("writ.activitypub")


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
            items = [p.to_ap_note() for p in posts]
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
    else:
        return (202, f"Accepted {atype}")


def _safe_fetch(url, timeout=10, max_size=5*1024*1024, headers=None):
    """HTTP GET with redirect validation and size limit."""
    if not _validate_url(url):
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

def _save_remote_avatar(avatar_url: str, local_username: str) -> str:
    """Download remote avatar and save, return profile_image URL."""
    from utils.storage import get_storage
    from uuid import uuid4
    if not _validate_url(avatar_url):
        return ""
    ext = avatar_url.rsplit(".", 1)[-1].lower() if "." in avatar_url else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    filename = f"{local_username}_{uuid4().hex[:8]}.{ext}"
    key = f"avatars/remote/{filename}"
    try:
        resp = _safe_fetch(avatar_url)
        if resp:
            storage = get_storage()
            ct = f"image/{ext}"
            return storage.save(key, resp.content, ct)
    except Exception as e:
        logger.warning("Failed to save remote avatar %s: %s", avatar_url, e)
    return ""


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

    # Extract avatar URL
    avatar_url = ""
    icon = data.get("icon", {})
    if isinstance(icon, dict):
        avatar_url = icon.get("url", "")
    elif isinstance(icon, list):
        avatar_url = icon[0].get("url", "") if icon else ""

    public_key_pem = ""
    if "publicKey" in data:
        public_key_pem = data["publicKey"].get("publicKeyPem", "")

    with get_session() as session:
        existing = session.query(User).filter_by(remote_url=actor_url).first()
        if existing:
            existing.public_key = public_key_pem
            existing.display_name = data.get("name", existing.display_name)
            existing.summary = data.get("summary", existing.summary)
            if avatar_url:
                existing.profile_image = _save_remote_avatar(avatar_url, local_username.replace("@", "_"))
            session.commit()
            return existing

        # Also check by username in case remote_url is missing/stale
        by_username = session.query(User).filter_by(username=local_username).first()
        if by_username:
            by_username.remote_url = actor_url
            by_username.public_key = public_key_pem or by_username.public_key
            by_username.display_name = data.get("name", by_username.display_name)
            by_username.summary = data.get("summary", by_username.summary)
            if avatar_url and not by_username.profile_image:
                by_username.profile_image = _save_remote_avatar(avatar_url, local_username.replace("@", "_"))
            session.commit()
            return by_username

        # Ensure uniqueness
        base_username = local_username
        counter = 1
        while session.query(User).filter_by(username=local_username).first():
            local_username = f"{base_username}_{counter}"
            counter += 1

        priv, pub = generate_keypair()
        profile_image = _save_remote_avatar(avatar_url, local_username.replace("@", "_")) if avatar_url else ""
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
        )
        session.add(user)
        session.commit()
        return user


def _handle_follow(activity: dict) -> tuple[int, str]:
    actor_url = activity["actor"] if isinstance(activity["actor"], str) else activity["actor"][0]
    object_url = activity["object"]
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


def _handle_accept(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    if isinstance(obj, dict):
        follower_url = obj.get("actor", "")
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
        actor_url = activity["actor"] if isinstance(activity["actor"], str) else activity["actor"][0]
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
        visibility = "public"
        if "https://www.w3.org/ns/activitystreams#Public" not in all_audiences:
            visibility = "home"

        with get_session() as session:
            existing = session.query(Post).filter_by(ap_id=post_id).first()
            if existing:
                return (200, "Already exists")

            reply_to_post = None
            if in_reply_to:
                reply_to_post = session.query(Post).filter_by(ap_id=in_reply_to).first()

            # Parse mentioned users from content
            import re
            mentioned_names = set(re.findall(r'@(\w+)', content or ""))
            mentioned_ids = []
            if mentioned_names:
                mentioned = session.query(User).filter(
                    User.username.in_(mentioned_names)
                ).all()
                mentioned_ids = [u.id for u in mentioned]

            # Process custom emoji tags
            _process_emoji_tags(obj.get("tag", []), session)
            session.flush()

            post = Post(
                author_id=actor.id,
                content=content,
                summary=summary,
                visibility=visibility,
                mentioned_user_ids=mentioned_ids,
                ap_id=post_id,
                in_reply_to_ap_id=in_reply_to,
                in_reply_to_id=reply_to_post.id if reply_to_post else None,
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
                from eventbus import broadcast
                broadcast("new_post", {"post_id": post.id, "author_id": actor.id})
            except Exception as e:
                logger.warning("broadcast failed: %s", e)

        return (200, "Created")
    return (200, "OK")


def _handle_like(activity: dict) -> tuple[int, str]:
    actor_url = activity["actor"] if isinstance(activity["actor"], str) else activity["actor"][0]
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
            import uuid
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
    actor_url = activity["actor"] if isinstance(activity["actor"], str) else activity["actor"][0]
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
            import uuid
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

    # Retry up to 3 times with exponential backoff
    import time as _time
    for attempt in range(3):
        try:
            httpx.post(inbox_url, content=body, headers=headers, timeout=10)
            return
        except Exception as e:
            if attempt < 2:
                _time.sleep(2 ** attempt)
            logger.warning("Failed to deliver to %s (attempt %d/3): %s", inbox_url, attempt + 1, e)


def send_to_shared_inbox(user: User, activity: dict):
    body = json.dumps(activity, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    date = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )

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

        existing = session.query(CustomEmoji).filter_by(keyword=keyword).first()
        if existing:
            if not domain or existing.domain == domain or existing.category != "remote":
                continue
            # Same keyword from a different domain — prefix to keep both
            keyword = f"{domain}_{keyword}"

        EMOJI_DIR = os.path.join(os.path.dirname(__file__), "web", "public", "emojis")
        import uuid
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
        sent.add(inbox)
        _post_to_inbox(inbox, activity, user)
