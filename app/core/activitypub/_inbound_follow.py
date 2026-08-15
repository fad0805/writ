import logging

from app.core.activitypub._fetch import _resolve_actor
from app.core.activitypub._outbound import _send_accept
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_notif_sound, broadcast_refresh_notifs
from app.db.database import get_session
from app.models import Follow, Notification, User
from app.utils.http import WRIT_USER_AGENT, validated_get
from app.utils.urls import parse_username_from_url

logger = logging.getLogger("writ.activitypub")


def _handle_follow(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    raw_object = activity.get("object", "")
    object_url = raw_object if isinstance(raw_object, str) else raw_object.get("id", "")
    activity_id = activity.get("id", "")

    local_username = parse_username_from_url(object_url)

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
            send_push_to_user(target.id, "follow" if accepted else "follow_request", follower.username)
            broadcast_notif_sound(target.id)

        # Send Accept only if auto-approved (not locked) — inside session so follower is still bound
        if accepted:
            _send_accept(actor_url, activity_id, target, follower=follower)

    return (200, "Followed")


def _handle_reject(activity: dict) -> tuple[int, str]:
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
            local_username = parse_username_from_url(follower_url)
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

    broadcast_refresh_notifs(local_user_id)
    return (200, "Rejected follow removed")

def _handle_accept(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    if isinstance(obj, dict):
        follower_url = obj.get("actor", "")
    elif isinstance(obj, str):
        try:
            resp = validated_get(obj, headers={"Accept": "application/activity+json, application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\"", "User-Agent": WRIT_USER_AGENT}, timeout=10)
            if resp is not None and resp.status_code == 200:
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

    local_username = parse_username_from_url(follower_url)
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
