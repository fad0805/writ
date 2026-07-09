"""add forward_to_remote to reports

Revision ID: cb1887b31a75
Revises: b4c23ee6c9f3
Create Date: 2026-07-09 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'cb1887b31a75'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('reports') as b:
        b.add_column(sa.Column('forward_to_remote', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reports') as b:
        b.drop_column('forward_to_remote')
