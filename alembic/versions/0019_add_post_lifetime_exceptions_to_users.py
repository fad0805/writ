"""add post_lifetime_exceptions to users

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-23

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0019'
down_revision: Union[str, None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "post_lifetime_exceptions" not in columns:
        op.add_column("users", sa.Column("post_lifetime_exceptions", sa.JSON, server_default="[]"))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "post_lifetime_exceptions" in columns:
        op.drop_column("users", "post_lifetime_exceptions")
