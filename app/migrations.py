"""Database migrations — extracted from models.py for modularity."""

import logging
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("writ.migrations")


def run_migrations(session: Session):
    _add_admin_role_column(session)
    _fill_post_numbers(session)
    _fill_novel_numbers(session)
    _add_admin_email_column(session)
    _add_federation_mode_column(session)
    _add_federation_block_reason_column(session)
    _sync_admin_roles(session)


def _add_federation_block_reason_column(session: Session):
    try:
        session.execute(text("ALTER TABLE federation_blocks ADD COLUMN reason VARCHAR(512) DEFAULT ''"))
        session.commit()
    except Exception:
        session.rollback()


def _add_admin_role_column(session: Session):
    try:
        session.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'user'"))
        session.commit()
    except Exception:
        session.rollback()


def _fill_post_numbers(session: Session):
    try:
        from app.models import Post
        import secrets
        for post in session.query(Post).filter(Post.number == "").all():
            post.number = secrets.token_hex(4)
        session.commit()
    except Exception:
        session.rollback()


def _fill_novel_numbers(session: Session):
    try:
        from app.models import Novel
        import secrets
        for novel in session.query(Novel).filter(Novel.number == "").all():
            novel.number = secrets.token_hex(4)
        session.commit()
    except Exception:
        session.rollback()


def _add_admin_email_column(session: Session):
    try:
        session.execute(text("ALTER TABLE server_settings ADD COLUMN admin_email VARCHAR(255) DEFAULT ''"))
        session.commit()
    except Exception:
        session.rollback()


def _add_federation_mode_column(session: Session):
    try:
        session.execute(text("ALTER TABLE server_settings ADD COLUMN federation_mode VARCHAR(16) DEFAULT 'blacklist'"))
        session.commit()
    except Exception:
        session.rollback()


def _sync_admin_roles(session: Session):
    try:
        from app.models import User
        session.query(User).filter(User.is_admin == True, User.role == "user").update({"role": "admin"})
        session.commit()
    except Exception:
        session.rollback()
