"""posts.boost_of_id ON DELETE SET NULL

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

FK_NAME_PG = "fk_posts_boost_of_id"


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        return
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint(FK_NAME_PG, type_="foreignkey")
        batch_op.create_foreign_key(
            FK_NAME_PG, "posts",
            ["boost_of_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        return
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint(FK_NAME_PG, type_="foreignkey")
        batch_op.create_foreign_key(
            FK_NAME_PG, "posts",
            ["boost_of_id"], ["id"],
        )
