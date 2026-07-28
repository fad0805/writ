"""Remove bumped_at from posts

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    try:
        op.drop_index("ix_posts_bumped", table_name="posts", if_exists=True)
    except Exception:
        pass
    op.drop_column("posts", "bumped_at")


def downgrade():
    add_column_safe("posts", sa.Column("bumped_at", sa.DateTime(), nullable=True))
    try:
        op.create_index("ix_posts_bumped", "posts", ["bumped_at"])
    except Exception:
        pass
