"""add_novel_is_sensitive

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09 16:58:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('novels') as b:
        b.add_column(sa.Column('is_sensitive', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('novels') as b:
        b.drop_column('is_sensitive')
