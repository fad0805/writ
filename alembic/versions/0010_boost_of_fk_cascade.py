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


def upgrade():
    op.drop_constraint("fk_posts_boost_of_id", "posts", type_="foreignkey")
    op.create_foreign_key(
        "fk_posts_boost_of_id",
        "posts", "posts",
        ["boost_of_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_posts_boost_of_id", "posts", type_="foreignkey")
    op.create_foreign_key(
        "fk_posts_boost_of_id",
        "posts", "posts",
        ["boost_of_id"], ["id"],
    )
