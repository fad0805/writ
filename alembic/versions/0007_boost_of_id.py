"""add boost_of_id column to posts

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-14

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('posts', sa.Column('boost_of_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_posts_boost_of_id', 'posts', 'posts', ['boost_of_id'], ['id'])
    op.create_index('ix_posts_boost_of_id', 'posts', ['boost_of_id'])


def downgrade() -> None:
    op.drop_index('ix_posts_boost_of_id', 'posts')
    op.drop_constraint('fk_posts_boost_of_id', 'posts', type_='foreignkey')
    op.drop_column('posts', 'boost_of_id')
