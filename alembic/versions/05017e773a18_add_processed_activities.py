"""add_processed_activities

Revision ID: 05017e773a18
Revises: 1a40d7ae394d
Create Date: 2026-07-09 16:58:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '05017e773a18'
down_revision: Union[str, Sequence[str], None] = '1a40d7ae394d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'processed_activities',
        sa.Column('id', sa.String(length=512), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('processed_activities')
