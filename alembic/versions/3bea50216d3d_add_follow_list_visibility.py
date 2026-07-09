"""add_follow_list_visibility

Revision ID: 3bea50216d3d
Revises: 359e3d7c2b15
Create Date: 2026-07-09 07:26:22.400940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3bea50216d3d'
down_revision: Union[str, Sequence[str], None] = '359e3d7c2b15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('follow_list_visibility', sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.drop_column('follow_list_visibility')
