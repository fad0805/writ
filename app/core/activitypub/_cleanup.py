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


_PROCESSED_ACTIVITY_RETENTION_DAYS = 7
_REMOTE_USER_CLEANUP_DAYS = 30


def _cleanup_remote_data():
    """Clean up expired media and old processed activities only. Remote posts are kept."""
    cutoff = datetime.datetime.now(datetime.timezone.utc)
    try:
        with get_session() as s:
            # Clean old processed activities (dedup tracking)
            pa_cutoff = cutoff - datetime.timedelta(days=_PROCESSED_ACTIVITY_RETENTION_DAYS)
            old_pa = s.query(ProcessedActivity).filter(
                ProcessedActivity.created_at < pa_cutoff
            ).limit(1000).all()
            for pa in old_pa:
                s.delete(pa)
            if old_pa:
                logger.info("Cleaned %d old processed activities", len(old_pa))

            # Clean stale remote users with no relationships (only if they have zero posts)
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
