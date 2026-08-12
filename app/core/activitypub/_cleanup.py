import os
import logging
import datetime

from sqlalchemy.exc import IntegrityError

from app.config.settings import BASE_URL
from app.db.database import get_session
from app.models import User, Post, Follow, RemoteMedia, ProcessedActivity
from app.utils.storage import get_storage
from app.utils.http import validated_get, WRIT_USER_AGENT

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
                    try:
                        # Follow/Post 외에도 Report, Like, Boost, Notification 등
                        # 다른 테이블이 아직 이 유저를 참조할 수 있다. savepoint로
                        # 격리해 실패해도 전체 정리 트랜잭션이 깨지지 않게 하고,
                        # 참조가 남은 유저는 이번엔 건너뛴다.
                        with s.begin_nested():
                            s.delete(u)
                            s.flush()
                        removed += 1
                    except IntegrityError:
                        continue
            if removed:
                logger.info("Cleaned %d stale remote users", removed)
            s.commit()
    except Exception as e:
        logger.error("Failed to cleanup remote data: %s", e, exc_info=True)
