"""Add remote_followers_count and remote_following_count to users

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    add_column_safe("users", sa.Column("remote_followers_count", sa.Integer, server_default="0"))
    add_column_safe("users", sa.Column("remote_following_count", sa.Integer, server_default="0"))


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("remote_followers_count")
        batch_op.drop_column("remote_following_count")
