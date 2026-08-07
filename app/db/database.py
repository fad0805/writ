import contextvars
from sqlalchemy import create_engine, text, inspect, event, func
from sqlalchemy.orm import Session

from sqlalchemy.orm import DeclarativeBase
from app.config.settings import DATABASE_URL

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


_SAFE_TABLE_NAMES = {"users", "posts", "novels", "episodes", "follows", "likes", "boosts",
                      "bookmarks", "notifications", "server_settings", "processed_activities",
                      "custom_emojis", "votes", "reactions", "user_blocks", "user_mutes",
                      "keyword_mutes", "series_mutes", "reports", "report_rules",
                      "federation_blocks", "federation_modes", "allowed_servers", "custom_fields",
                      "episode_comments", "series_notices", "remote_followers",
                      "mastodon_apps", "mastodon_access_tokens",
                      "announcements", "announcement_reads", "announcement_votes"}


def init_db():
    Base.metadata.create_all(engine)
    # Direct SQL fallback — add missing columns that Alembic may have skipped
    _add_missing_columns()
    # Create additional composite indexes for performance
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
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_episodes_novel_created ON episodes(novel_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_series_notices_novel_created ON series_notices(novel_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_in_reply_to_deleted ON posts(in_reply_to_id, is_deleted)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_likes_user_post ON likes(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_boosts_user_post ON boosts(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bookmarks_user_post ON bookmarks(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_votes_user_post ON votes(user_id, post_id)"))
            conn.commit()
    except Exception:
        pass


def _add_missing_columns():
    """Add columns that exist in SQLAlchemy models but are missing from DB tables."""
    try:
        inspector = inspect(engine)
    except Exception:
        return
    _add_cols("users", inspector, [
        ("enable_reactions", "BOOLEAN DEFAULT TRUE"),
        ("is_deactivated", "BOOLEAN DEFAULT FALSE"),
        ("is_deceased", "BOOLEAN DEFAULT FALSE"),
        ("is_sensitive", "BOOLEAN DEFAULT FALSE"),
        ("show_badge", "BOOLEAN DEFAULT FALSE"),
        ("is_bot", "BOOLEAN DEFAULT FALSE"),
        ("is_limited", "BOOLEAN DEFAULT FALSE"),
        ("is_locked", "BOOLEAN DEFAULT FALSE"),
        ("display_handle", "VARCHAR(256) DEFAULT ''"),
        ("follow_list_visibility", "VARCHAR(16) DEFAULT 'public'"),
        ("episode_default_visibility", "VARCHAR(16) DEFAULT 'public'"),
        ("session_token", "VARCHAR(256) DEFAULT ''"),
        ("moderation_note", "TEXT DEFAULT ''"),
        ("moved_to", "VARCHAR(512) DEFAULT ''"),
        ("remote_followers_count", "INTEGER DEFAULT 0"),
        ("remote_following_count", "INTEGER DEFAULT 0"),
        ("custom_fields", "JSON DEFAULT '[]'"),
        ("profile_hashtags", "JSON DEFAULT '[]'"),
        ("pinned_posts", "JSON DEFAULT '[]'"),
        ("pinned_series", "JSON DEFAULT '[]'"),
        ("aliases", "JSON DEFAULT '[]'"),
    ])
    _add_cols("posts", inspector, [
        ("is_sensitive", "BOOLEAN DEFAULT FALSE"),
        ("original_visibility", "VARCHAR(16) DEFAULT ''"),
        ("media_attachments", "JSON DEFAULT '[]'"),
        ("poll_data", "JSON"),
        ("is_dm", "BOOLEAN DEFAULT FALSE"),
        ("novel_id", "INTEGER"),
        ("episode_id", "INTEGER"),
        ("mentioned_user_ids", "JSON DEFAULT '[]'"),
        ("in_reply_to_ap_id", "VARCHAR(1024) DEFAULT ''"),
        ("bumped_at", "TIMESTAMP"),
    ])
    _add_cols("novels", inspector, [
        ("is_sensitive", "BOOLEAN DEFAULT FALSE"),
    ])
    _add_cols("episodes", inspector, [
        ("summary", "TEXT DEFAULT ''"),
        ("comment", "TEXT DEFAULT ''"),
    ])


def _add_cols(table: str, inspector, cols: list[tuple[str, str]]):
    if table not in _SAFE_TABLE_NAMES:
        raise ValueError(f"Invalid table name: {table}")
    try:
        existing = {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return
    col_defs = [f"ADD COLUMN {col_name} {col_def}" for col_name, col_def in cols if col_name not in existing]
    if not col_defs:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} {', '.join(col_defs)}"))
            conn.commit()
    except Exception:
        pass


class Base(DeclarativeBase):
    pass

