"""fill missing columns

Revision ID: 0001
Revises: None
Create Date: 2026-07-10

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS: list[tuple[str, str, str]] = [
    # users
    ("users", "enable_reactions", "BOOLEAN"),
    ("users", "is_deactivated", "BOOLEAN"),
    ("users", "is_deceased", "BOOLEAN"),
    ("users", "is_sensitive", "BOOLEAN"),
    ("users", "show_badge", "BOOLEAN"),
    ("users", "is_bot", "BOOLEAN"),
    ("users", "is_limited", "BOOLEAN"),
    ("users", "is_locked", "BOOLEAN"),
    ("users", "display_handle", "VARCHAR(256)"),
    ("users", "follow_list_visibility", "VARCHAR(16)"),
    ("users", "episode_default_visibility", "VARCHAR(16)"),
    ("users", "session_token", "VARCHAR(256)"),
    ("users", "moderation_note", "TEXT"),
    ("users", "moved_to", "VARCHAR(512)"),
    ("users", "custom_fields", "JSON"),
    ("users", "profile_hashtags", "JSON"),
    ("users", "pinned_posts", "JSON"),
    ("users", "pinned_series", "JSON"),
    ("users", "aliases", "JSON"),
    # posts
    ("posts", "is_sensitive", "BOOLEAN"),
    ("posts", "original_visibility", "VARCHAR(16)"),
    ("posts", "media_attachments", "JSON"),
    ("posts", "poll_data", "JSON"),
    ("posts", "is_dm", "BOOLEAN"),
    ("posts", "novel_id", "INTEGER"),
    ("posts", "episode_id", "INTEGER"),
    ("posts", "mentioned_user_ids", "JSON"),
    ("posts", "in_reply_to_ap_id", "VARCHAR(1024)"),
    ("posts", "bumped_at", "DATETIME"),
    # novels
    ("novels", "is_sensitive", "BOOLEAN"),
    # episodes
    ("episodes", "summary", "TEXT"),
    ("episodes", "comment", "TEXT"),
]


def upgrade() -> None:
    for table, col, typ in _COLUMNS:
        try:
            op.add_column(table, sa.Column(col, sa.Text()))
        except Exception:
            pass


def downgrade() -> None:
    pass
