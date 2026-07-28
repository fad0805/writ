"""Add audio_url to episodes

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    add_column_safe("episodes", sa.Column("audio_url", sa.String(512), server_default=""))


def downgrade():
    op.drop_column("episodes", "audio_url")
