"""add explore index

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-23

"""

from typing import Sequence, Union
from alembic import op


revision: str = '0020'
down_revision: Union[str, None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_posts_explore
        ON posts (created_at DESC)
        WHERE visibility = 'public' AND is_deleted = 0 AND in_reply_to_id IS NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_posts_explore", table_name="posts")
