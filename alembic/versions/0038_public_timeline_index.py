"""add composite index for public timeline ordering

연합/로컬 타임라인의 WHERE(visibility, is_deleted) + ORDER BY
(created_at DESC, id DESC)를 한 인덱스로 서빙한다. 기존 ix_posts_timeline
부분 인덱스는 SQLite 플래너가 매칭하지 못하고, (created_at DESC)만 커버해
공개 글 수가 늘면 전체 정렬로 폴백할 수 있다.

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0038'
down_revision: Union[str, None] = '0037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_posts_vis_deleted_created
        ON posts (visibility, is_deleted, created_at DESC, id DESC)
    """)


def downgrade() -> None:
    op.drop_index("ix_posts_vis_deleted_created", table_name="posts")

