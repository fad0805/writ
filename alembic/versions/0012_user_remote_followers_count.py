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


def _column_exists(table, column):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        if not _column_exists("users", "remote_followers_count"):
            batch_op.add_column(sa.Column("remote_followers_count", sa.Integer, server_default="0"))
        if not _column_exists("users", "remote_following_count"):
            batch_op.add_column(sa.Column("remote_following_count", sa.Integer, server_default="0"))


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        if _column_exists("users", "remote_followers_count"):
            batch_op.drop_column("remote_followers_count")
        if _column_exists("users", "remote_following_count"):
            batch_op.drop_column("remote_following_count")
