"""add boost_of_id column to posts

Revision ID: 0007
Revises: 29696bcd0cf9
Create Date: 2026-07-14

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe


revision: str = '0007'
down_revision: Union[str, None] = '29696bcd0cf9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_safe("posts", sa.Column("boost_of_id", sa.Integer(), nullable=True))
    try:
        op.create_foreign_key("fk_posts_boost_of_id", "posts", "posts", ["boost_of_id"], ["id"])
    except Exception:
        pass
    try:
        op.create_index("ix_posts_boost_of_id", "posts", ["boost_of_id"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_posts_boost_of_id", "posts")
    except Exception:
        pass
    try:
        op.drop_constraint("fk_posts_boost_of_id", "posts", type_="foreignkey")
    except Exception:
        pass
    op.drop_column("posts", "boost_of_id")
