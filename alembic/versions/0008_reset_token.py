"""add reset_token column

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    add_column_safe("users", sa.Column("reset_token", sa.String(128), server_default=""))


def downgrade():
    op.drop_column("users", "reset_token")
