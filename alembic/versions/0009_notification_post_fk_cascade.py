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

FK_NAME_PG = "notifications_post_id_fkey"


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        return
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_constraint(FK_NAME_PG, type_="foreignkey")
        batch_op.create_foreign_key(
            FK_NAME_PG, "posts",
            ["post_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        return
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_constraint(FK_NAME_PG, type_="foreignkey")
        batch_op.create_foreign_key(
            FK_NAME_PG, "posts",
            ["post_id"], ["id"],
        )
