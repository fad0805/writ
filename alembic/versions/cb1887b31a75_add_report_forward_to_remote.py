"""add_report_forward_to_remote

Revision ID: cb1887b31a75
Revises: 6fa3f3809001
Create Date: 2026-07-09 15:45:40.077123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cb1887b31a75'
down_revision: Union[str, Sequence[str], None] = '6fa3f3809001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('reports') as b:
        b.add_column(sa.Column('forward_to_remote', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reports') as b:
        b.drop_column('forward_to_remote')
