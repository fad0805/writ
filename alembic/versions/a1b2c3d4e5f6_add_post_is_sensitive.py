"""add_post_is_sensitive

Revision ID: a1b2c3d4e5f6
Revises: 9ee0190db478
Create Date: 2026-07-09 16:58:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('posts') as b:
        b.add_column(sa.Column('is_sensitive', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('posts') as b:
        b.drop_column('is_sensitive')
