import contextvars
import logging

from sqlalchemy import create_engine, event, func, text
from sqlalchemy.orm import DeclarativeBase, Session

from app.config.settings import DATABASE_URL

logger = logging.getLogger("writ.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
_request_session: contextvars.ContextVar = contextvars.ContextVar("request_session", default=None)

_DIALECT = "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql"

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, connection_record):
        try:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
        except Exception:
            pass
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=20,
        max_overflow=30,
        pool_use_lifo=True,
        pool_recycle=300,
        pool_timeout=15,
        pool_pre_ping=True,
    )


def get_db():
    """FastAPI Depends용 - 요청마다 세션을 생성하고 자동으로 닫는다."""
    sess = Session(engine, expire_on_commit=False)
    _request_session.set(sess)
    try:
        yield sess
    finally:
        _request_session.set(None)
        sess.close()


def get_session():
    sess = _request_session.get()
    if sess is not None:
        return sess
    return Session(engine, expire_on_commit=False)


def username_prefix_like(col, prefix):
    """username 접두사 LIKE 표현식. 전용 인덱스를 타도록 dialect별로 분기한다.

    - Postgres: lower(username) text_pattern_ops 인덱스용 lower(username) LIKE 'prefix%'
    - SQLite: username COLLATE NOCASE 인덱스용 username LIKE 'prefix%'
      (SQLite의 LIKE는 기본적으로 ASCII 대소문자를 구분하지 않는다)
    """
    if _DIALECT == "sqlite":
        return col.like(prefix + "%")
    return func.lower(col).like(prefix.lower() + "%")


def init_db():
    """빈 DB를 현재 모델 기준으로 구성한다 (테스트 등 전용).

    스키마 관리의 단일 진실원은 Alembic 마이그레이션이다(alembic upgrade head).
    프로덕션 부팅은 start.sh가 마이그레이션을 실행하므로 이 함수를 쓰지 않는다.
    """
    Base.metadata.create_all(engine)
    # 모델에 선언되지 않은 복합 성능 인덱스 보강
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_author_created ON posts(author_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_author_deleted_created ON posts(author_id, is_deleted, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_follow_activity_id ON follows(activity_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notif_user_created ON notifications(user_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notif_user_type ON notifications(user_id, notification_type)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notif_user_read ON notifications(user_id, is_read)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_follows_follower_following ON follows(follower_id, following_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_follows_follower_accepted ON follows(follower_id, following_id, accepted)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_is_remote ON users(is_remote)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_visibility_deleted ON posts(visibility, is_deleted)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_vis_deleted_created ON posts(visibility, is_deleted, created_at DESC, id DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_episodes_novel_created ON episodes(novel_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_series_notices_novel_created ON series_notices(novel_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_in_reply_to_deleted ON posts(in_reply_to_id, is_deleted)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_likes_user_post ON likes(user_id, post_id)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_boosts_user_post ON boosts(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bookmarks_user_post ON bookmarks(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_votes_user_post ON votes(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_episode_views_user_episode_viewed ON episode_views(user_id, episode_id, viewed_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_episode_views_episode ON episode_views(episode_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_episodes_novel_number ON episodes(novel_id, episode_number)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_author_vis_deleted_created ON posts(author_id, visibility, is_deleted, created_at, id)"))
            conn.commit()
    except Exception:
        logger.warning("init_db: 인덱스 생성 실패", exc_info=True)


class Base(DeclarativeBase):
    pass

