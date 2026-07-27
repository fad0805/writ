"""Add audio_url to episodes

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("episodes", sa.Column("audio_url", sa.String(512), server_default=""))


def downgrade():
    op.drop_column("episodes", "audio_url")
