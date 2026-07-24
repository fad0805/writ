"""Remove bumped_at from posts

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_posts_bumped", table_name="posts", if_exists=True)
    op.drop_column("posts", "bumped_at")


def downgrade():
    op.add_column("posts", sa.Column("bumped_at", sa.DateTime(), nullable=True))
    op.create_index("ix_posts_bumped", "posts", ["bumped_at"])
