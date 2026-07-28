"""add missing columns (proper types)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_safe("users", sa.Column("enable_reactions", sa.Boolean(), default=True))
    add_column_safe("users", sa.Column("is_deactivated", sa.Boolean(), default=False))
    add_column_safe("users", sa.Column("is_deceased", sa.Boolean(), default=False))
    add_column_safe("users", sa.Column("is_sensitive", sa.Boolean(), default=False))
    add_column_safe("users", sa.Column("show_badge", sa.Boolean(), default=False))
    add_column_safe("users", sa.Column("is_bot", sa.Boolean(), default=False))
    add_column_safe("users", sa.Column("is_limited", sa.Boolean(), default=False))
    add_column_safe("users", sa.Column("is_locked", sa.Boolean(), default=False))
    add_column_safe("users", sa.Column("display_handle", sa.String(256), default=""))
    add_column_safe("users", sa.Column("follow_list_visibility", sa.String(16), default="public"))
    add_column_safe("users", sa.Column("episode_default_visibility", sa.String(16), default="public"))
    add_column_safe("users", sa.Column("session_token", sa.String(256), default=""))
    add_column_safe("users", sa.Column("moderation_note", sa.Text(), default=""))
    add_column_safe("users", sa.Column("moved_to", sa.String(512), default=""))
    add_column_safe("users", sa.Column("custom_fields", sa.JSON(), default=list))
    add_column_safe("users", sa.Column("profile_hashtags", sa.JSON(), default=list))
    add_column_safe("users", sa.Column("pinned_posts", sa.JSON(), default=list))
    add_column_safe("users", sa.Column("pinned_series", sa.JSON(), default=list))
    add_column_safe("users", sa.Column("aliases", sa.JSON(), default=list))
    add_column_safe("posts", sa.Column("is_sensitive", sa.Boolean(), default=False))
    add_column_safe("posts", sa.Column("original_visibility", sa.String(16), default=""))
    add_column_safe("posts", sa.Column("media_attachments", sa.JSON(), default=list))
    add_column_safe("posts", sa.Column("poll_data", sa.JSON(), nullable=True))
    add_column_safe("posts", sa.Column("is_dm", sa.Boolean(), default=False))
    add_column_safe("posts", sa.Column("novel_id", sa.Integer(), nullable=True))
    add_column_safe("posts", sa.Column("episode_id", sa.Integer(), nullable=True))
    add_column_safe("posts", sa.Column("mentioned_user_ids", sa.JSON(), default=list))
    add_column_safe("posts", sa.Column("in_reply_to_ap_id", sa.String(1024), default=""))
    add_column_safe("posts", sa.Column("bumped_at", sa.DateTime(), nullable=True))
    add_column_safe("novels", sa.Column("is_sensitive", sa.Boolean(), default=False))
    add_column_safe("episodes", sa.Column("summary", sa.Text(), default=""))
    add_column_safe("episodes", sa.Column("comment", sa.Text(), default=""))


def downgrade() -> None:
    pass
