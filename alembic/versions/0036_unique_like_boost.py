"""Add unique constraint on likes/boosts (user_id, post_id)

동시 좋아요/부스트(TOCTOU)로 중복 행이 생기는 것을 DB 레벨에서 막는다.
기존 비유니크 복합 인덱스(ix_likes_user_post / ix_boosts_user_post)를
유니크로 교체하고, 기존 중복 데이터는 최소 id 행만 남기고 정리한다.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0036'
down_revision: Union[str, None] = '0035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dedupe(bind, table: str) -> None:
    bind.exec_driver_sql(
        f"DELETE FROM {table} WHERE id NOT IN ("
        f"SELECT MIN(id) FROM {table} GROUP BY user_id, post_id)"
    )


def upgrade() -> None:
    bind = op.get_context().bind
    _dedupe(bind, "likes")
    _dedupe(bind, "boosts")
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_likes_user_post")
        op.execute("DROP INDEX IF EXISTS ix_boosts_user_post")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_likes_user_post ON likes(user_id, post_id)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_boosts_user_post ON boosts(user_id, post_id)")
    else:
        op.execute("DROP INDEX IF EXISTS ix_likes_user_post")
        op.execute("DROP INDEX IF EXISTS ix_boosts_user_post")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_likes_user_post ON likes(user_id, post_id)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_boosts_user_post ON boosts(user_id, post_id)")


def downgrade() -> None:
    bind = op.get_context().bind
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS uq_likes_user_post")
        op.execute("DROP INDEX IF EXISTS uq_boosts_user_post")
    else:
        op.execute("DROP INDEX IF EXISTS ix_likes_user_post")
        op.execute("DROP INDEX IF EXISTS ix_boosts_user_post")
    op.execute("CREATE INDEX IF NOT EXISTS ix_likes_user_post ON likes(user_id, post_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_boosts_user_post ON boosts(user_id, post_id)")
