"""add post_lifetime to users

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-23

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0018'
down_revision: Union[str, None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "post_lifetime" not in columns:
        op.add_column("users", sa.Column("post_lifetime", sa.Integer, server_default="0"))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "post_lifetime" in columns:
        op.drop_column("users", "post_lifetime")
