import json
import time
import uuid
import threading
import base64
import hashlib
import datetime
import logging

import httpx
from sqlalchemy.orm import Session, selectinload

from app.config.settings import BASE_URL, SECRET_KEY
from app.db.database import get_session
from app.models import User, Post, Follow, PendingDelivery
from app.utils.crypto import sign_string, get_private_key
from app.core.federation import federation_allowed
from app.utils.http import validate_url
from urllib.parse import urlparse

logger = logging.getLogger("writ.activitypub")


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


def _send_delete_post(post: Post, sender: User):
    note_id = post.ap_id
    delete = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{sender.actor_uri()}/deletes/{post.id}",
        "type": "Delete",
        "actor": sender.actor_uri(),
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "object": {
            "type": "Note",
            "id": note_id,
            "attributedTo": sender.actor_uri()
        }
    }
    try:
        broadcast_to_followers(sender, delete)
    except Exception as e:
        logger.error("Failed to broadcast Delete: %s", e, exc_info=True)
    # Also send Delete directly to parent author's inbox for remote replies
    if post.in_reply_to_ap_id:
        try:
            with get_session() as s:
                parent = s.query(Post).filter_by(ap_id=post.in_reply_to_ap_id).first()
                if parent and parent.author and parent.author.is_remote:
                    inbox = parent.author.shared_inbox_url or parent.author.inbox_url
                    if inbox:
                        _post_to_inbox(inbox, delete, sender)
        except Exception as e:
            logger.error("Failed to send Delete to parent author: %s", e, exc_info=True)


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
    if not validate_url(inbox_url):
        return
    body = json.dumps(activity, ensure_ascii=True, sort_keys=True).encode("utf-8")
    print(f"DEBUG_BODY_LENGTH: {len(body)}")
    print(f"DEBUG_BODY: {body.decode('utf-8')}") # 실제 전송되는 JSON
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    digest_header = f"SHA-256={digest}" # 공백 없음 확인
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    date = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

    parsed = urlparse(inbox_url)
    path = parsed.path or "/"
    print(f"DEBUG_VERIFY: incoming_inbox={inbox_url}, parsed_host={parsed.netloc}")
    signed_string = (
        f"(request-target): post {path}\n"
        f"host: {parsed.netloc}\n"
        f"date: {date}\n"
        f"digest: {digest_header}"
    )
    print(f"DEBUG_SIGNED_STRING: {repr(signed_string)}") # \n 같은 제어문자까지 다 보게 repr() 사용

    signature = sign_string(signed_string, get_private_key(sender, SECRET_KEY))
    signature_header = (
        f'keyId="{sender.actor_uri()}#main-key",'
        f'algorithm="rsa-sha256",'
        f'headers="(request-target) host date digest",'
        f'signature="{signature}"'
    )

    headers = {
        "Content-Type": "application/activity+json",
        "Signature": signature_header,
        "Date": date,
        "Digest": digest_header,
        "Host": parsed.netloc,
    }

    # Immediate delivery attempt with inline retry
    if _deliver_sync(inbox_url, body, headers):
        return

    # Queue for background retry if immediate delivery fails
    with get_session() as session:
        session.add(PendingDelivery(
            inbox_url=inbox_url,
            activity_json=json.dumps(activity, ensure_ascii=True, sort_keys=True),
            sender_id=sender.id,
            status="pending",
        ))
        session.commit()


def send_to_shared_inbox(user: User, activity: dict):
    with get_session() as session:
        followers = session.query(Follow).options(
            selectinload(Follow.following)
        ).filter(
            Follow.follower_id == user.id,
            Follow.following.has(is_remote=True),
        ).all()

        inboxes = set()
        for f in followers:
            target = f.following
            inbox = target.shared_inbox_url or target.inbox_url
            if not inbox:
                continue
            if inbox in inboxes:
                continue
            inboxes.add(inbox)
    for inbox in inboxes:
        _post_to_inbox(inbox, activity, user)


def broadcast_to_followers(user: User, activity: dict):
    with get_session() as session:
        followers = session.query(Follow).options(
            selectinload(Follow.follower)
        ).filter(
            Follow.following_id == user.id,
            Follow.follower.has(is_remote=True),
        ).all()

        inboxes = set()
        for f in followers:
            inbox = f.follower.shared_inbox_url or f.follower.inbox_url
            if not inbox:
                continue
            if inbox in inboxes:
                continue
            domain = urlparse(inbox).hostname or ""
            if not federation_allowed(domain):
                continue
            inboxes.add(inbox)
    for inbox in inboxes:
        _post_to_inbox(inbox, activity, user)


def _author_inbox(post: Post) -> str | None:
    """Inbox URL to notify the post author about interactions."""
    return post.author.shared_inbox_url or post.author.inbox_url


def _undo_like_activity(user: User, post: Post, reaction: str | None, target_id: str = ""):
    """Build an ActivityPub Undo-Like object."""
    return {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{BASE_URL}/likes/{uuid.uuid4()}#undo",
        "type": "Undo",
        "actor": user.actor_uri(),
        "object": {
            "id": target_id or f"{BASE_URL}/likes/{uuid.uuid4()}",
            "type": "Like",
            "actor": user.actor_uri(),
            "object": post.ap_id,
            "content": reaction or "★",
            "_misskey_reaction": reaction or "★",
        },
    }


def _fanout_to_followers(db: Session, user: User, activity: dict, action: str = "boost", threaded: bool = False):
    """Send an activity to the remote inboxes of the user's followers."""
    try:
        followers = db.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == user.id).all()
        sent_inboxes = set()
        for follower in followers:
            if follower.is_remote and (follower.shared_inbox_url or follower.inbox_url):
                inbox = follower.shared_inbox_url or follower.inbox_url
                if inbox not in sent_inboxes:
                    sent_inboxes.add(inbox)
                    try:
                        if threaded:
                            threading.Thread(target=_post_to_inbox, args=(inbox, activity, user), daemon=True).start()
                        else:
                            _post_to_inbox(inbox, activity, user)
                    except Exception as e:
                        logger.error("Failed to fan-out %s to inbox %s: %s", action, inbox, e, exc_info=True)
    except Exception as e:
        logger.error("Failed to query followers for %s fan-out: %s", action, e, exc_info=True)
