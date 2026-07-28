"""Add view_mode and image_urls to episodes

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    add_column_safe("episodes", sa.Column("view_mode", sa.String(16), server_default="text"))
    add_column_safe("episodes", sa.Column("image_urls", sa.JSON(), server_default="[]"))


def downgrade():
    op.drop_column("episodes", "image_urls")
    op.drop_column("episodes", "view_mode")
