"""add expires_at to posts

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-23

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe


revision: str = '0017'
down_revision: Union[str, None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_safe("posts", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    try:
        op.create_index("ix_posts_expires_at", "posts", ["expires_at"])
    except Exception:
        pass


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("posts")]
    if "expires_at" in columns:
        try:
            op.drop_index("ix_posts_expires_at", "posts")
        except Exception:
            pass
        op.drop_column("posts", "expires_at")
