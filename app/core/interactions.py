"""Shared interaction logic used by both internal API and Mastodon-compat API."""

import json
import logging
import uuid

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User, Post, Like, Boost, Notification, CustomEmoji
from app.config.settings import BASE_URL
from app.core.activitypub import _post_to_inbox, _author_inbox, _undo_like_activity, _fanout_to_followers
from app.core.visibility import _can_view
from app.core.push import send_push_to_user
from app.core.broadcast import broadcast_post
from app.core.threads import spawn
from app.core.timeline_stream import (
    broadcast_refresh_notifs, broadcast_notif_sound,
    broadcast_reaction_update, broadcast_delete,
)
from app.utils.emoji import _emoji_url

logger = logging.getLogger("writ.post_interactions")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_post(db: Session, post_id: int):
    """Fetch a non-deleted post by id."""
    return db.query(Post).filter_by(id=post_id, is_deleted=False).first()


def _resolve_boost_target(db: Session, post: Post) -> Post:
    """Resolve a boost pointer post to the original post it boosts."""
    if not post.boost_of_id:
        return post
    original = db.query(Post).get(post.boost_of_id)
    return original or post


def _get_reactions(db: Session, post_id: int) -> dict:
    """Aggregate per-reaction counts for a post, keyed by display reaction."""
    reactions = {}
    rows = db.query(Like.reaction, func.count(Like.id)).filter(
        Like.post_id == post_id
    ).group_by(Like.reaction).order_by(func.min(Like.id)).all()
    for reaction, count in rows:
        reactions[reaction or "★"] = count
    return reactions


def _add_like_notif(db: Session, post: Post, user: User, post_id: int, reaction: str):
    """Create a like notification for the post author if it doesn't exist yet."""
    if post.author_id == user.id:
        return
    existing_notif = db.query(Notification).filter_by(
        user_id=post.author_id, from_user_id=user.id,
        notification_type="like", post_id=post_id,
    ).first()
    if existing_notif:
        return
    _notif_meta = {"reaction": reaction} if reaction else {}
    db.add(Notification(
        user_id=post.author_id, from_user_id=user.id,
        notification_type="like", post_id=post_id,
        metadata_json=json.dumps(_notif_meta) if _notif_meta else "",
    ))


def _add_boost_notif(db: Session, post: Post, user: User, post_id: int):
    """Create a boost notification for the post author if it doesn't exist yet."""
    if post.author_id == user.id:
        return
    existing_notif = db.query(Notification).filter_by(
        user_id=post.author_id, from_user_id=user.id,
        notification_type="boost", post_id=post_id,
    ).first()
    if existing_notif:
        return
    db.add(Notification(
        user_id=post.author_id, from_user_id=user.id,
        notification_type="boost", post_id=post_id,
    ))


def _notify_author(db: Session, post: Post, user: User, post_id: int, kind: str):
    """Push + sound notification for the post author about a like/boost."""
    if post.author_id == user.id:
        return
    broadcast_refresh_notifs(post.author_id)
    send_push_to_user(post.author_id, kind, user.username, post_id)
    broadcast_notif_sound(post.author_id)


def _dedupe_like(db: Session, user: User, post_id: int):
    """Keep only the most recent Like row for a user+post."""
    db.flush()
    keep_id = db.query(Like.id).filter_by(user_id=user.id, post_id=post_id).order_by(Like.id.desc()).first()
    if keep_id:
        db.query(Like).filter(Like.user_id == user.id, Like.post_id == post_id, Like.id != keep_id[0]).delete(synchronize_session=False)
    db.commit()


def _delete_like(db: Session, user: User, post: Post, match_reaction: str | None = None):
    """Remove the user's like (optionally only when the reaction matches).

    Broadcasts updated reaction counts and refreshes the author's notification
    list. Returns the removed (reaction, ap_id), or None if nothing was removed.
    """
    existing = db.query(Like).filter_by(user_id=user.id, post_id=post.id).first()
    if not existing:
        return None
    if match_reaction is not None and existing.reaction != match_reaction:
        return None
    removed_reaction = existing.reaction
    removed_ap_id = existing.ap_id
    db.delete(existing)
    db.query(Notification).filter_by(
        from_user_id=user.id, notification_type="like", post_id=post.id
    ).delete()
    db.commit()
    broadcast_reaction_update(post.id, _get_reactions(db, post.id))
    broadcast_refresh_notifs(post.author_id)
    return removed_reaction, removed_ap_id


# ---------------------------------------------------------------------------
# Like / Unlike
# ---------------------------------------------------------------------------

def like_post(db: Session, user: User, post_id: int, reaction: str = "★"):
    post = _get_post(db, post_id)
    if not post or not _can_view(post, user, db):
        return

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post_id).first()

    if not existing:
        try:
            db.add(Like(user_id=user.id, post_id=post_id, reaction=reaction))
            _add_like_notif(db, post, user, post_id, reaction)
            _dedupe_like(db, user, post_id)
        except IntegrityError:
            db.rollback()
            return
        broadcast_reaction_update(post_id, _get_reactions(db, post_id))
        _notify_author(db, post, user, post_id, "like")

    inbox = _author_inbox(post)
    if post.author.is_remote and inbox:
        like_id = f"{BASE_URL}/likes/{uuid.uuid4()}"
        like_rec = existing or db.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
        if like_rec:
            like_rec.ap_id = like_id
            like_rec.reaction = reaction
            db.commit()
        _react = reaction or "★"
        is_custom = _react != "★"
        activity_type = "EmojiReact" if is_custom else "Like"
        like_activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": like_id,
            "type": activity_type,
            "actor": user.actor_uri(),
            "object": post.ap_id,
            "to": [post.author.actor_uri()],
            "cc": ["https://www.w3.org/ns/activitystreams#Public"],
        }
        if is_custom or _react:
            like_activity["content"] = _react
            like_activity["_misskey_reaction"] = _react
        try:
            _post_to_inbox(inbox, like_activity, user)
        except Exception:
            pass


def unlike_post(db: Session, user: User, post_id: int):
    post = _get_post(db, post_id)
    if not post:
        return

    removed = _delete_like(db, user, post)
    removed_reaction = removed[0] if removed else None
    like_id = removed[1] if removed else ""

    inbox = _author_inbox(post)
    if post.author.is_remote and inbox:
        undo = _undo_like_activity(user, post, removed_reaction, like_id)
        try:
            _post_to_inbox(inbox, undo, user)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Boost / Unboost
# ---------------------------------------------------------------------------

def boost_post(db: Session, user: User, post_id: int):
    post = _get_post(db, post_id)
    if not post or not _can_view(post, user, db):
        return
    post = _resolve_boost_target(db, post)
    post_id = post.id
    if post.visibility == "mention" or (post.author_id != user.id and post.visibility == "followers"):
        return

    existing = db.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
    if not existing:
        try:
            db.add(Boost(user_id=user.id, post_id=post_id))
            db.add(Post(
                author_id=user.id,
                content="",
                boost_of_id=post_id,
                visibility=post.visibility or "public",
            ))
            _add_boost_notif(db, post, user, post_id)
            db.commit()
        except IntegrityError:
            db.rollback()
            return

        try:
            _boosts_count = db.query(Boost).filter_by(post_id=post_id).count()
            broadcast_post({
                "id": post.id, "type": "update",
                "boosts_count": _boosts_count,
            }, post.author_id, post.visibility or "public")
        except Exception as e:
            logger.error("Failed to broadcast boost update: %s", e, exc_info=True)

        _notify_author(db, post, user, post_id, "boost")

        announce_id = f"{BASE_URL}/boosts/{uuid.uuid4()}"
        author_inbox = _author_inbox(post)

        if post.author.is_remote and author_inbox:
            boost_rec = db.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
            if boost_rec:
                boost_rec.ap_id = announce_id
                db.commit()

        announce = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": announce_id,
            "type": "Announce",
            "actor": user.actor_uri(),
            "object": post.ap_id,
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [post.author.actor_uri(), f'{BASE_URL}/users/{user.username}/followers'],
        }

        if post.author.is_remote and author_inbox:
            try:
                spawn(_post_to_inbox, author_inbox, announce, user)
            except Exception as e:
                logger.error("Failed to send boost to author inbox: %s", e, exc_info=True)

        _fanout_to_followers(db, user, announce, action="boost", threaded=True)


def unboost_post(db: Session, user: User, post_id: int):
    post = _get_post(db, post_id)
    if not post:
        return
    post = _resolve_boost_target(db, post)
    post_id = post.id

    existing = db.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
    announce_id = existing.ap_id if existing and existing.ap_id else ""
    if existing:
        _bp = db.query(Post.id).filter_by(author_id=user.id, boost_of_id=post_id).first()
        _bp_id = _bp[0] if _bp else None
        db.delete(existing)
        db.query(Post).filter_by(author_id=user.id, boost_of_id=post_id).delete()
        db.query(Notification).filter_by(
            from_user_id=user.id, notification_type="boost", post_id=post_id
        ).delete()
        remaining = db.query(Boost).filter_by(post_id=post_id).count()
        db.commit()
        if _bp_id:
            try:
                broadcast_delete(_bp_id)
            except Exception as e:
                logger.error("Failed to broadcast boost pointer delete: %s", e, exc_info=True)
        if post.author_id != user.id:
            broadcast_refresh_notifs(post.author_id)
        try:
            broadcast_post({
                "id": post_id, "type": "update",
                "boosts_count": remaining,
                "boosted_by": [],
            }, post.author_id, post.visibility or "public")
        except Exception as e:
            logger.error("Failed to broadcast unboost update: %s", e, exc_info=True)

        undo_id = f"{BASE_URL}/boosts/{uuid.uuid4()}#undo"
        target_announce_id = announce_id or f"{BASE_URL}/boosts/{uuid.uuid4()}"
        undo = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": undo_id,
            "type": "Undo",
            "actor": user.actor_uri(),
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [post.author.actor_uri(), f'{BASE_URL}/users/{user.username}/followers'],
            "object": {
                "id": target_announce_id,
                "type": "Announce",
                "actor": user.actor_uri(),
                "object": post.ap_id,
            },
        }
        author_inbox = _author_inbox(post)
        if post.author.is_remote and author_inbox:
            try:
                spawn(_post_to_inbox, author_inbox, undo, user)
            except Exception as e:
                logger.error("Failed to send unboost to author inbox: %s", e, exc_info=True)
        _fanout_to_followers(db, user, undo, action="unboost")


# ---------------------------------------------------------------------------
# React / Unreact
# ---------------------------------------------------------------------------

def react_post(db: Session, user: User, post_id: int, emoji: str):
    post = _get_post(db, post_id)
    if not post or not _can_view(post, user, db):
        return

    post_author_id = post.author_id
    post_ap_id = post.ap_id
    post_author_is_remote = post.author.is_remote
    post_author_shared_inbox = post.author.shared_inbox_url if post_author_is_remote else None

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
    old_reaction = existing.reaction if existing else None
    is_new = existing is None

    if existing:
        existing.reaction = emoji
        existing_notif = db.query(Notification).filter_by(
            user_id=post_author_id, from_user_id=user.id, notification_type="like", post_id=post_id
        ).first() if post_author_id != user.id else None
        if existing_notif:
            _notif_meta = {"reaction": emoji} if emoji else {}
            existing_notif.metadata_json = json.dumps(_notif_meta) if _notif_meta else ""
    else:
        try:
            db.add(Like(user_id=user.id, post_id=post_id, reaction=emoji))
            _add_like_notif(db, post, user, post_id, emoji)
            _dedupe_like(db, user, post_id)
        except IntegrityError:
            db.rollback()
            return

    broadcast_reaction_update(post_id, _get_reactions(db, post_id))
    if post_author_id != user.id:
        broadcast_refresh_notifs(post_author_id)

    if post_author_is_remote and post_author_shared_inbox:
        _tag = []
        if emoji.startswith(":") and emoji.endswith(":"):
            _kw = emoji[1:-1]
            _emoji_row = db.query(CustomEmoji).filter_by(keyword=_kw, domain="").first()
            if not _emoji_row:
                _emoji_row = db.query(CustomEmoji).filter_by(keyword=_kw).first()
            if _emoji_row and _emoji_row.file_name:
                _emoji_img = _emoji_url(_emoji_row.file_name, _emoji_row.domain or "", _emoji_row.category or "")
                if not _emoji_img.startswith("http"):
                    _emoji_img = f"{BASE_URL}{_emoji_img}"
                if _emoji_img:
                    _tag = [{"type": "Emoji", "id": f"{BASE_URL}/emojis/{_kw}", "name": emoji, "icon": {"type": "Image", "mediaType": "image/png", "url": _emoji_img}}]
        like_activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{BASE_URL}/likes/{uuid.uuid4()}",
            "type": "Like",
            "actor": user.actor_uri(),
            "object": post_ap_id,
            "content": emoji,
            "_misskey_reaction": emoji,
        }
        if _tag:
            like_activity["tag"] = _tag
        if is_new or old_reaction != emoji:
            try:
                _post_to_inbox(post_author_shared_inbox, like_activity, user)
            except Exception:
                pass


def unreact_post(db: Session, user: User, post_id: int, emoji: str | None = None):
    post = _get_post(db, post_id)
    if not post:
        return

    post_author_is_remote = post.author.is_remote
    post_author_shared_inbox = post.author.shared_inbox_url if post_author_is_remote else None

    removed = _delete_like(db, user, post, match_reaction=emoji)
    if removed and post_author_is_remote and post_author_shared_inbox:
        undo = _undo_like_activity(user, post, removed[0])
        try:
            _post_to_inbox(post_author_shared_inbox, undo, user)
        except Exception:
            pass
