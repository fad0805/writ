"""add reading_direction to episodes

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-01

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe


revision: str = '0030'
down_revision: Union[str, None] = '0029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_safe("episodes", sa.Column("reading_direction", sa.String(8), server_default="ltr"))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("episodes")]
    if "reading_direction" in columns:
        op.drop_column("episodes", "reading_direction")
