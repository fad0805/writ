"""is_completed_to_status

Revision ID: 359e3d7c2b15
Revises: b4c23ee6c9f3
Create Date: 2026-07-09 07:12:34.020299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '359e3d7c2b15'
down_revision: Union[str, Sequence[str], None] = 'b4c23ee6c9f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('novels') as b:
        b.add_column(sa.Column('status', sa.String(length=16), nullable=True))
    op.execute("UPDATE novels SET status = 'completed' WHERE is_completed = 1")
    op.execute("UPDATE novels SET status = 'ongoing' WHERE status IS NULL")
    with op.batch_alter_table('novels') as b:
        b.alter_column('status', existing_type=sa.String(length=16), nullable=False)
        b.drop_column('is_completed')

    with op.batch_alter_table('users') as b:
        b.drop_column('is_pinned')


def downgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('is_pinned', sa.BOOLEAN(), server_default=sa.text('0'), nullable=True))

    with op.batch_alter_table('novels') as b:
        b.add_column(sa.Column('is_completed', sa.BOOLEAN(), nullable=True))
    op.execute("UPDATE novels SET is_completed = 1 WHERE status = 'completed'")
    op.execute("UPDATE novels SET is_completed = 0 WHERE status != 'completed' OR status IS NULL")
    with op.batch_alter_table('novels') as b:
        b.drop_column('status')
