"""add_pending_deliveries

Revision ID: 1eaa49508f37
Revises: cb1887b31a75
Create Date: 2026-07-09 15:45:40.077123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1eaa49508f37'
down_revision: Union[str, Sequence[str], None] = 'cb1887b31a75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pending_deliveries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inbox_url', sa.String(length=512), nullable=False),
        sa.Column('activity_json', sa.Text(), nullable=False),
        sa.Column('sender_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('pending_deliveries')
