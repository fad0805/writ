"""Deduplicate likes and add unique constraint on (user_id, post_id)

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _constraint_exists(table, constraint_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = [c["name"] for c in inspector.get_unique_constraints(table)]
    return constraint_name in constraints


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM likes
        WHERE id NOT IN (
            SELECT MIN(id) FROM likes GROUP BY user_id, post_id
        )
    """))
    if not _constraint_exists("likes", "uq_likes_user_post"):
        with op.batch_alter_table("likes") as batch_op:
            batch_op.create_unique_constraint("uq_likes_user_post", ["user_id", "post_id"])


def downgrade():
    if _constraint_exists("likes", "uq_likes_user_post"):
        with op.batch_alter_table("likes") as batch_op:
            batch_op.drop_constraint("uq_likes_user_post", type_="unique")
