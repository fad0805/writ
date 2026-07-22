"""add expires_at to votes

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-21 19:49:12.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("votes", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("votes", "expires_at")
