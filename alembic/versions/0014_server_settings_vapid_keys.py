"""add vapid_private_key and vapid_public_key to server_settings

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-19 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("server_settings", sa.Column("vapid_private_key", sa.Text(), server_default=""))
    op.add_column("server_settings", sa.Column("vapid_public_key", sa.Text(), server_default=""))


def downgrade():
    op.drop_column("server_settings", "vapid_private_key")
    op.drop_column("server_settings", "vapid_public_key")
