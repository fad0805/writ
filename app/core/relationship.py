"""Shared interaction logic used by both internal API and Mastodon-compat API."""

import json
import logging
import threading
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User, Post, Follow, Like, Boost, Bookmark, Notification, CustomEmoji, UserMute, UserBlock
from app.config.settings import BASE_URL
from app.core.activitypub import _post_to_inbox
from app.core.push import send_push_to_user
from app.core.broadcast import broadcast_post
from app.core.timeline_stream import (
    broadcast_refresh_notifs, broadcast_notif_sound,
    broadcast_reaction_update, broadcast_delete,
)
from app.serializers import _user_json
from app.utils.emoji import _emoji_url

logger = logging.getLogger("writ.relationships")


def follow_user(db: Session, user: User, target: User):
    if target.id == user.id:
        return
    existing = db.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
    if not existing:
        accepted = not target.is_locked
        db.add(Follow(follower_id=user.id, following_id=target.id, accepted=accepted))
        existing_notif = db.query(Notification).filter_by(
            from_user_id=user.id, user_id=target.id
        ).filter(Notification.notification_type.in_(["follow", "follow_request"])).first()
        if not existing_notif:
            db.add(Notification(
                user_id=target.id, from_user_id=user.id,
                notification_type="follow_request" if not accepted else "follow"
            ))
        db.commit()
        broadcast_refresh_notifs(target.id)
        send_push_to_user(target.id, "follow" if accepted else "follow_request", user.username)
        broadcast_notif_sound(target.id)

    if target.is_remote and target.inbox_url:
        follow_activity = {
            "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
            "id": f"{BASE_URL}/activities/follow/{uuid.uuid4()}",
            "type": "Follow",
            "actor": user.actor_uri(),
            "object": target.actor_uri(),
            "to": [target.actor_uri()],
        }
        follow_rec = db.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
        if follow_rec:
            follow_rec.activity_id = follow_activity["id"]
            db.commit()
        try:
            _post_to_inbox(target.inbox_url, follow_activity, user)
        except Exception as e:
            logger.error("Failed to send follow to remote inbox: %s", e, exc_info=True)


def unfollow_user(db: Session, user: User, target: User):
    if target.id == user.id:
        return
    existing = db.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
    if existing:
        db.delete(existing)
        db.query(Notification).filter(
            Notification.from_user_id == user.id,
            Notification.user_id == target.id,
            Notification.notification_type.in_(["follow", "follow_request"])
        ).delete(synchronize_session=False)
        db.commit()
        try:
            broadcast_refresh_notifs(target.id)
        except Exception:
            pass
        if target.is_remote and target.inbox_url:
            follow_activity_id = f"{user.actor_uri()}#follows/{target.id}"
            undo = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{user.actor_uri()}#follows/{target.id}/undo",
                "type": "Undo",
                "actor": user.actor_uri(),
                "object": {
                    "id": follow_activity_id,
                    "type": "Follow",
                    "actor": user.actor_uri(),
                    "object": target.actor_uri(),
                },
            }
            try:
                _post_to_inbox(target.inbox_url, undo, user)
            except Exception as e:
                logger.error("Failed to send Undo Follow: %s", e, exc_info=True)


def mute_user(db: Session, user: User, target: User, duration: int = 0, hide_notifications: bool = False):
    if target.id == user.id:
        return
    existing = db.query(UserMute).filter_by(user_id=user.id, target_user_id=target.id).first()
    if existing:
        existing.duration = duration
        existing.hide_notifications = hide_notifications
    else:
        db.add(UserMute(user_id=user.id, target_user_id=target.id, duration=duration, hide_notifications=hide_notifications))
    db.commit()


def unmute_user(db: Session, user: User, target: User):
    db.query(UserMute).filter_by(user_id=user.id, target_user_id=target.id).delete()
    db.commit()


def block_user(db: Session, user: User, target: User):
    if target.id == user.id:
        return
    existing = db.query(UserBlock).filter_by(user_id=user.id, target_user_id=target.id).first()
    if existing:
        return
    db.add(UserBlock(user_id=user.id, target_user_id=target.id))
    db.query(Follow).filter_by(follower_id=user.id, following_id=target.id).delete()
    db.query(Follow).filter_by(follower_id=target.id, following_id=user.id).delete()
    db.commit()
    if target.is_remote and (target.shared_inbox_url or target.inbox_url):
        block_id = f"{BASE_URL}/users/{user.username}/status/activities/block/{target.id}"
        block_activity = {
            "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
            "type": "Block",
            "id": block_id,
            "actor": user.actor_uri(),
            "to": [target.remote_url],
            "object": target.remote_url,
        }
        try:
            _post_to_inbox(target.shared_inbox_url or target.inbox_url, block_activity, user)
        except Exception as e:
            logger.error("Failed to send Block: %s", e, exc_info=True)


def unblock_user(db: Session, user: User, target: User):
    db.query(UserBlock).filter_by(user_id=user.id, target_user_id=target.id).delete()
    db.commit()
    if target.is_remote and target.remote_url and (target.shared_inbox_url or target.inbox_url):
        block_id = f"{BASE_URL}/users/{user.username}/status/activities/block/{target.id}"
        undo_activity = {
            "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
            "type": "Undo",
            "id": f"{BASE_URL}/users/{user.username}/status/activities/undo/{target.id}",
            "actor": user.actor_uri(),
            "to": [target.remote_url],
            "object": {
                "id": block_id,
                "type": "Block",
                "actor": user.actor_uri(),
                "object": target.remote_url,
            },
        }
        try:
            _post_to_inbox(target.shared_inbox_url or target.inbox_url, undo_activity, user)
        except Exception as e:
            logger.error("Failed to send Undo Block: %s", e, exc_info=True)

