"""notifications.post_id ON DELETE SET NULL

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("notifications_post_id_fkey", "notifications", type_="foreignkey")
    op.create_foreign_key(
        "notifications_post_id_fkey",
        "notifications", "posts",
        ["post_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("notifications_post_id_fkey", "notifications", type_="foreignkey")
    op.create_foreign_key(
        "notifications_post_id_fkey",
        "notifications", "posts",
        ["post_id"], ["id"],
    )
