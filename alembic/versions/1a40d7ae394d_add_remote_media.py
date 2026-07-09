"""add_remote_media

Revision ID: 1a40d7ae394d
Revises: b4a7e32d9f01
Create Date: 2026-07-09 16:58:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '1a40d7ae394d'
down_revision: Union[str, Sequence[str], None] = 'b4a7e32d9f01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'remote_media',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('remote_url', sa.String(length=1024), nullable=False),
        sa.Column('local_url', sa.String(length=512), nullable=False),
        sa.Column('size', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_remote_media_remote_url', 'remote_media', ['remote_url'])


def downgrade() -> None:
    op.drop_index('ix_remote_media_remote_url')
    op.drop_table('remote_media')
