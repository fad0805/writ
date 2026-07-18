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


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM likes
        WHERE id NOT IN (
            SELECT MIN(id) FROM likes GROUP BY user_id, post_id
        )
    """))
    with op.batch_alter_table("likes") as batch_op:
        batch_op.create_unique_constraint("uq_likes_user_post", ["user_id", "post_id"])


def downgrade():
    with op.batch_alter_table("likes") as batch_op:
        batch_op.drop_constraint("uq_likes_user_post", type_="unique")
