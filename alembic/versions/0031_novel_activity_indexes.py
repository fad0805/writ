"""Add composite indexes for novel activity ordering

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-01
"""
from typing import Sequence, Union
from alembic import op

revision: str = '0031'
down_revision: Union[str, None] = '0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_episodes_novel_created
        ON episodes (novel_id, created_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_series_notices_novel_created
        ON series_notices (novel_id, created_at)
    """)


def downgrade() -> None:
    op.drop_index("ix_episodes_novel_created", table_name="episodes")
    op.drop_index("ix_series_notices_novel_created", table_name="series_notices")
