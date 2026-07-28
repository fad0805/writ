"""Add display_name to tags

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    add_column_safe("tags", sa.Column("display_name", sa.String(128), nullable=True))
    op.execute("UPDATE tags SET display_name = name WHERE display_name IS NULL")


def downgrade():
    op.drop_column("tags", "display_name")
