"""add activity_id to follows

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-11

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("follows", sa.Column("activity_id", sa.String(1024), default=""))


def downgrade() -> None:
    op.drop_column("follows", "activity_id")
