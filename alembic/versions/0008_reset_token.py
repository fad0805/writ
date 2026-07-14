"""add reset_token column

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("reset_token", sa.String(128), server_default=""))


def downgrade():
    op.drop_column("users", "reset_token")
