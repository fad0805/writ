"""add notify_on_post to follows

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-11

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("follows", sa.Column("notify_on_post", sa.Boolean(), default=False))


def downgrade() -> None:
    op.drop_column("follows", "notify_on_post")
