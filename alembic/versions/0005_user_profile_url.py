"""add profile_url to users

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "profile_url" not in columns:
        op.add_column("users", sa.Column("profile_url", sa.String(512), server_default=""))


def downgrade() -> None:
    op.drop_column("users", "profile_url")
