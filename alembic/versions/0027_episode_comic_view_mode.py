"""Add comic_view_mode and reading_direction to episodes

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("episodes", sa.Column("comic_view_mode", sa.String(16), server_default="paged"))
    op.add_column("episodes", sa.Column("reading_direction", sa.String(8), server_default="ltr"))


def downgrade():
    op.drop_column("episodes", "reading_direction")
    op.drop_column("episodes", "comic_view_mode")
