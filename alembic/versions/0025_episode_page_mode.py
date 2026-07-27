"""Add page_mode to episodes

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("episodes", sa.Column("page_mode", sa.Boolean(), server_default="false"))


def downgrade():
    op.drop_column("episodes", "page_mode")
