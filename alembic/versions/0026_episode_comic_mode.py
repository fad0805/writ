"""Add view_mode and image_urls to episodes

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("episodes", sa.Column("view_mode", sa.String(16), server_default="text"))
    op.add_column("episodes", sa.Column("image_urls", sa.JSON(), server_default="[]"))


def downgrade():
    op.drop_column("episodes", "image_urls")
    op.drop_column("episodes", "view_mode")
