"""Add composite indexes for timeline performance

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-29
"""
from typing import Sequence, Union
from alembic import op

revision: str = '0028'
down_revision: Union[str, None] = '0027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_posts_author_created
        ON posts (author_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_posts_timeline
        ON posts (created_at DESC)
        WHERE is_deleted = FALSE AND visibility = 'public'
    """)


def downgrade() -> None:
    op.drop_index("ix_posts_timeline", table_name="posts")
    op.drop_index("ix_posts_author_created", table_name="posts")
