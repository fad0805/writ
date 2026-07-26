import os
import logging
import datetime

from app.config.settings import BASE_URL
from app.db.database import get_session
from app.models import User, Post, Follow, RemoteMedia, ProcessedActivity
from app.utils.storage import get_storage
from app.core.activitypub._utils import _validated_get, WRIT_USER_AGENT

logger = logging.getLogger("writ.activitypub")


def _cleanup_expired_media():
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
        logger.error("Failed to cleanup expired media: %s", e, exc_info=True)


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
            if old_remote_posts:
                now_check = datetime.datetime.now(datetime.timezone.utc)
                old_ids = []
                for p in old_remote_posts:
                    age = (now_check - p.created_at).total_seconds() / 86400 if p.created_at else 0
                    if age < _REMOTE_POST_RETENTION_DAYS - 1:
                        logger.warning("Skipping remote post %d (age=%.1fd, cutoff=%dd)", p.id, age, _REMOTE_POST_RETENTION_DAYS)
                        continue
                    old_ids.append(p.id)
                if not old_ids:
                    logger.info("All %d candidate remote posts were within retention period", len(old_remote_posts))
                else:
                    s.query(Post).filter(Post.in_reply_to_id.in_(old_ids)).update(
                        {Post.in_reply_to_id: None}, synchronize_session=False
                    )
                    s.query(Post).filter(Post.boost_of_id.in_(old_ids)).update(
                        {Post.boost_of_id: None}, synchronize_session=False
                    )
                    for p in old_remote_posts:
                        if p.id in old_ids:
                            s.delete(p)
                    logger.info("Cleaned %d old remote posts (skipped %d within retention)", len(old_ids), len(old_remote_posts) - len(old_ids))

            # Clean old processed activities (dedup tracking)
            pa_cutoff = cutoff - datetime.timedelta(days=_PROCESSED_ACTIVITY_RETENTION_DAYS)
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
        logger.error("Failed to cleanup remote data: %s", e, exc_info=True)
