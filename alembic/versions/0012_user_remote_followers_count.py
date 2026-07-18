"""Add remote_followers_count and remote_following_count to users

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("remote_followers_count", sa.Integer, server_default="0"))
    op.add_column("users", sa.Column("remote_following_count", sa.Integer, server_default="0"))


def downgrade():
    op.drop_column("users", "remote_followers_count")
    op.drop_column("users", "remote_following_count")
