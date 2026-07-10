"""add missing columns (proper types)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add(table: str, col: sa.Column):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns(table)]
    if col.name not in columns:
        op.add_column(table, col)


def upgrade() -> None:
    _add("users", sa.Column("enable_reactions", sa.Boolean(), default=True))
    _add("users", sa.Column("is_deactivated", sa.Boolean(), default=False))
    _add("users", sa.Column("is_deceased", sa.Boolean(), default=False))
    _add("users", sa.Column("is_sensitive", sa.Boolean(), default=False))
    _add("users", sa.Column("show_badge", sa.Boolean(), default=False))
    _add("users", sa.Column("is_bot", sa.Boolean(), default=False))
    _add("users", sa.Column("is_limited", sa.Boolean(), default=False))
    _add("users", sa.Column("is_locked", sa.Boolean(), default=False))
    _add("users", sa.Column("display_handle", sa.String(256), default=""))
    _add("users", sa.Column("follow_list_visibility", sa.String(16), default="public"))
    _add("users", sa.Column("episode_default_visibility", sa.String(16), default="public"))
    _add("users", sa.Column("session_token", sa.String(256), default=""))
    _add("users", sa.Column("moderation_note", sa.Text(), default=""))
    _add("users", sa.Column("moved_to", sa.String(512), default=""))
    _add("users", sa.Column("custom_fields", sa.JSON(), default=list))
    _add("users", sa.Column("profile_hashtags", sa.JSON(), default=list))
    _add("users", sa.Column("pinned_posts", sa.JSON(), default=list))
    _add("users", sa.Column("pinned_series", sa.JSON(), default=list))
    _add("users", sa.Column("aliases", sa.JSON(), default=list))
    _add("posts", sa.Column("is_sensitive", sa.Boolean(), default=False))
    _add("posts", sa.Column("original_visibility", sa.String(16), default=""))
    _add("posts", sa.Column("media_attachments", sa.JSON(), default=list))
    _add("posts", sa.Column("poll_data", sa.JSON(), nullable=True))
    _add("posts", sa.Column("is_dm", sa.Boolean(), default=False))
    _add("posts", sa.Column("novel_id", sa.Integer(), nullable=True))
    _add("posts", sa.Column("episode_id", sa.Integer(), nullable=True))
    _add("posts", sa.Column("mentioned_user_ids", sa.JSON(), default=list))
    _add("posts", sa.Column("in_reply_to_ap_id", sa.String(1024), default=""))
    _add("posts", sa.Column("bumped_at", sa.DateTime(), nullable=True))
    _add("novels", sa.Column("is_sensitive", sa.Boolean(), default=False))
    _add("episodes", sa.Column("summary", sa.Text(), default=""))
    _add("episodes", sa.Column("comment", sa.Text(), default=""))


def downgrade() -> None:
    pass
