"""add rule_ids to reports

Revision ID: b4a7e32d9f01
Revises: 1eaa49508f37
Create Date: 2026-07-09 16:58:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b4a7e32d9f01'
down_revision: Union[str, Sequence[str], None] = '1eaa49508f37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('reports') as b:
        b.add_column(sa.Column('rule_ids', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reports') as b:
        b.drop_column('rule_ids')
