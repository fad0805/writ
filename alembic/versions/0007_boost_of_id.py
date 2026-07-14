"""add boost_of_id column to posts

Revision ID: 0007
Revises: 29696bcd0cf9
Create Date: 2026-07-14

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '29696bcd0cf9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("posts")]
    if "boost_of_id" not in columns:
        op.add_column("posts", sa.Column("boost_of_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_posts_boost_of_id", "posts", "posts", ["boost_of_id"], ["id"])
        op.create_index("ix_posts_boost_of_id", "posts", ["boost_of_id"])


def downgrade() -> None:
    op.drop_index("ix_posts_boost_of_id", "posts")
    op.drop_constraint("fk_posts_boost_of_id", "posts", type_="foreignkey")
    op.drop_column("posts", "boost_of_id")
