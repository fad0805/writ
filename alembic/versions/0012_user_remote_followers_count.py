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
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("remote_followers_count", sa.Integer, server_default="0"))
        batch_op.add_column(sa.Column("remote_following_count", sa.Integer, server_default="0"))


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("remote_followers_count")
        batch_op.drop_column("remote_following_count")
