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

logger = logging.getLogger("writ.post_interactions")


def _can_view(post, viewer, session):
    if post.is_deleted:
        return False
    if viewer and post.author_id == viewer.id:
        return True
    v = post.visibility or "public"
    if v in ("public", "home"):
        return True
    if not viewer:
        return False
    if v == "followers":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return session.query(Follow).filter_by(
            follower_id=viewer.id, following_id=post.author_id, accepted=True
        ).first() is not None
    if v == "mention":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return False
    return True


def like_post(db: Session, user: User, post_id: int, reaction: str = "★"):
    post = db.query(Post).filter_by(id=post_id, is_deleted=False).first()
    if not post or not _can_view(post, user, db):
        return

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
    existing_notif = db.query(Notification).filter_by(
        user_id=post.author_id, from_user_id=user.id, notification_type="like", post_id=post_id
    ).first() if post.author_id != user.id else None

    if not existing:
        db.add(Like(user_id=user.id, post_id=post_id, reaction=reaction))
        if post.author_id != user.id and not existing_notif:
            _notif_meta = {"reaction": reaction} if reaction else {}
            db.add(Notification(
                user_id=post.author_id, from_user_id=user.id,
                notification_type="like", post_id=post_id,
                metadata_json=json.dumps(_notif_meta) if _notif_meta else ""
            ))
        db.flush()
        keep_id = db.query(Like.id).filter_by(user_id=user.id, post_id=post_id).order_by(Like.id.desc()).first()
        if keep_id:
            db.query(Like).filter(Like.user_id == user.id, Like.post_id == post_id, Like.id != keep_id[0]).delete(synchronize_session=False)
        db.commit()
        _reactions = {}
        for _react, _cnt in db.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
            _reactions[_react or "★"] = _cnt
        broadcast_reaction_update(post_id, _reactions)
        if post.author_id != user.id:
            broadcast_refresh_notifs(post.author_id)
            send_push_to_user(post.author_id, "like", user.username, post_id)
            broadcast_notif_sound(post.author_id)

    inbox = post.author.shared_inbox_url or post.author.inbox_url
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
    post = db.query(Post).filter_by(id=post_id, is_deleted=False).first()
    if not post:
        return

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
    like_id = existing.ap_id if existing and existing.ap_id else ""
    existing_reaction = existing.reaction if existing else None
    if existing:
        db.delete(existing)
        db.query(Notification).filter_by(
            from_user_id=user.id, notification_type="like", post_id=post_id
        ).delete()
        db.commit()
        _reactions = {}
        for _react, _cnt in db.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
            _reactions[_react or "★"] = _cnt
        broadcast_reaction_update(post_id, _reactions)
        broadcast_refresh_notifs(post.author_id)

    inbox = post.author.shared_inbox_url or post.author.inbox_url
    if post.author.is_remote and inbox:
        undo = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{BASE_URL}/likes/{uuid.uuid4()}#undo",
            "type": "Undo",
            "actor": user.actor_uri(),
            "object": {
                "id": like_id or f"{BASE_URL}/likes/{uuid.uuid4()}",
                "type": "Like",
                "actor": user.actor_uri(),
                "object": post.ap_id,
                "content": existing_reaction or "★",
                "_misskey_reaction": existing_reaction or "★",
            },
        }
        try:
            _post_to_inbox(inbox, undo, user)
        except Exception:
            pass


def boost_post(db: Session, user: User, post_id: int):
    post = db.query(Post).filter_by(id=post_id, is_deleted=False).first()
    if not post or not _can_view(post, user, db):
        return
    if post.boost_of_id:
        post = db.query(Post).get(post.boost_of_id)
        post_id = post.id
    if post.visibility == "mention" or (post.author_id != user.id and post.visibility == "followers"):
        return

    existing = db.query(Boost).filter_by(user_id=user.id, post_id=post_id).first()
    existing_notif = db.query(Notification).filter_by(
        user_id=post.author_id, from_user_id=user.id, notification_type="boost", post_id=post_id
    ).first() if post.author_id != user.id else None
    if not existing:
        db.add(Boost(user_id=user.id, post_id=post_id))
        boost_post = Post(
            author_id=user.id,
            content="",
            boost_of_id=post_id,
            visibility=post.visibility or "public",
        )
        db.add(boost_post)
        if post.author_id != user.id and not existing_notif:
            db.add(Notification(
                user_id=post.author_id, from_user_id=user.id,
                notification_type="boost", post_id=post_id
            ))
        db.commit()

        try:
            _boosts_count = db.query(Boost).filter_by(post_id=post_id).count()
            broadcast_post({
                "id": post.id, "type": "update",
                "boosts_count": _boosts_count,
            }, post.author_id, post.visibility or "public")
        except Exception as e:
            logger.error("Failed to broadcast boost update: %s", e, exc_info=True)

        if post.author_id != user.id:
            broadcast_refresh_notifs(post.author_id)
            send_push_to_user(post.author_id, "boost", user.username, post_id)
            broadcast_notif_sound(post.author_id)

        announce_id = f"{BASE_URL}/boosts/{uuid.uuid4()}"
        author_inbox = post.author.shared_inbox_url or post.author.inbox_url

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
                threading.Thread(target=_post_to_inbox, args=(author_inbox, announce, user), daemon=True).start()
            except Exception as e:
                logger.error("Failed to send boost to author inbox: %s", e, exc_info=True)

        try:
            followers = db.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == user.id).all()
            sent_inboxes = set()
            for follower in followers:
                if follower.is_remote and (follower.shared_inbox_url or follower.inbox_url):
                    inbox = follower.shared_inbox_url or follower.inbox_url
                    if inbox not in sent_inboxes:
                        sent_inboxes.add(inbox)
                        try:
                            threading.Thread(target=_post_to_inbox, args=(inbox, announce, user), daemon=True).start()
                        except Exception as e:
                            logger.error("Failed to fan-out boost to inbox %s: %s", inbox, e, exc_info=True)
        except Exception as e:
            logger.error("Failed to query followers for boost fan-out: %s", e, exc_info=True)


def unboost_post(db: Session, user: User, post_id: int):
    post = db.query(Post).filter_by(id=post_id, is_deleted=False).first()
    if not post:
        return
    if post.boost_of_id:
        post = db.query(Post).get(post.boost_of_id)
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
        author_inbox = post.author.shared_inbox_url or post.author.inbox_url
        if post.author.is_remote and author_inbox:
            try:
                threading.Thread(target=_post_to_inbox, args=(author_inbox, undo, user), daemon=True).start()
            except Exception as e:
                logger.error("Failed to send unboost to author inbox: %s", e, exc_info=True)
        try:
            followers = db.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == user.id).all()
            sent_inboxes = set()
            for follower in followers:
                if follower.is_remote and (follower.shared_inbox_url or follower.inbox_url):
                    inbox = follower.shared_inbox_url or follower.inbox_url
                    if inbox not in sent_inboxes:
                        sent_inboxes.add(inbox)
                        try:
                            _post_to_inbox(inbox, undo, user)
                        except Exception as e:
                            logger.error("Failed to fan-out unboost to inbox %s: %s", inbox, e, exc_info=True)
        except Exception as e:
            logger.error("Failed to query followers for unboost fan-out: %s", e, exc_info=True)


def react_post(db: Session, user: User, post_id: int, emoji: str):
    post = db.query(Post).filter_by(id=post_id, is_deleted=False).first()
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
        db.add(Like(user_id=user.id, post_id=post_id, reaction=emoji))
        if post_author_id != user.id:
            existing_notif = db.query(Notification).filter_by(
                user_id=post_author_id, from_user_id=user.id, notification_type="like", post_id=post_id
            ).first()
            if not existing_notif:
                _notif_meta = {"reaction": emoji} if emoji else {}
                db.add(Notification(
                    user_id=post_author_id, from_user_id=user.id,
                    notification_type="like", post_id=post_id,
                    metadata_json=json.dumps(_notif_meta) if _notif_meta else ""
                ))
    db.flush()
    keep_id = db.query(Like.id).filter_by(user_id=user.id, post_id=post_id).order_by(Like.id.desc()).first()
    if keep_id:
        db.query(Like).filter(Like.user_id == user.id, Like.post_id == post_id, Like.id != keep_id[0]).delete(synchronize_session=False)
    db.commit()

    _reactions = {}
    for _react, _cnt in db.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
        _reactions[_react or "★"] = _cnt
    broadcast_reaction_update(post_id, _reactions)
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
    post = db.query(Post).filter_by(id=post_id, is_deleted=False).first()
    if not post:
        return

    post_ap_id = post.ap_id
    post_author_is_remote = post.author.is_remote
    post_author_shared_inbox = post.author.shared_inbox_url if post_author_is_remote else None

    existing = db.query(Like).filter_by(user_id=user.id, post_id=post_id).first()
    existing_reaction = existing.reaction if existing else None
    if existing and (emoji is None or existing.reaction == emoji):
        db.delete(existing)
        db.query(Notification).filter_by(
            from_user_id=user.id, notification_type="like", post_id=post_id
        ).delete()
        db.commit()
        _reactions = {}
        for _react, _cnt in db.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post_id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
            _reactions[_react or "★"] = _cnt
        broadcast_reaction_update(post_id, _reactions)
        broadcast_refresh_notifs(post.author_id)
        if post_author_is_remote and post_author_shared_inbox:
            undo = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/likes/{uuid.uuid4()}#undo",
                "type": "Undo",
                "actor": user.actor_uri(),
                "object": {
                    "id": f"{BASE_URL}/likes/{uuid.uuid4()}",
                    "type": "Like",
                    "actor": user.actor_uri(),
                    "object": post_ap_id,
                    "content": existing_reaction or "★",
                    "_misskey_reaction": existing_reaction or "★",
                },
            }
            try:
                _post_to_inbox(post_author_shared_inbox, undo, user)
            except Exception:
                pass

